"""Dynamic Historical Rankings — configurable weighted composite rankings."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.luck import luck_metrics
from fantasy.analytics.standings import career_standings, season_standings
from utils import apply_league_filter

try:
    from style import inject_css
except ImportError:
    def inject_css() -> None:
        pass


def render(conn) -> None:
    inject_css()
    st.title("📊 Dynamic Rankings")
    st.caption("Configure weights to build your own composite ranking system.")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    lid: str | None = st.session_state.get("selected_league_id")

    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    seasons = sorted(matchups_df["season"].unique())

    scope_opts = ["All Seasons", "Regular Season Only", "Playoffs Only"] + [str(s) for s in seasons]
    scope = st.selectbox("Scope", scope_opts, key="dr_scope")

    if scope == "Regular Season Only":
        view_df = matchups_df[~matchups_df["is_playoff"].fillna(False) & ~matchups_df["is_championship"].fillna(False)]
    elif scope == "Playoffs Only":
        view_df = matchups_df[matchups_df["is_playoff"].fillna(False) | matchups_df["is_championship"].fillna(False)]
    elif scope in [str(s) for s in seasons]:
        view_df = matchups_df[matchups_df["season"] == int(scope)]
    else:
        view_df = matchups_df

    if view_df.empty:
        st.info("No data for this scope.")
        return

    st.divider()
    st.subheader("Weight Configuration")
    st.caption("Adjust sliders. All weights are normalized — relative values matter, not absolutes.")

    col1, col2, col3 = st.columns(3)
    with col1:
        w_wins = st.slider("Win% weight", 0, 10, 4, key="dr_w_wins")
        w_pf = st.slider("Points For weight", 0, 10, 3, key="dr_w_pf")
    with col2:
        w_allplay = st.slider("All-Play% weight", 0, 10, 3, key="dr_w_allplay")
        w_luck = st.slider("Luck (expected wins) weight", 0, 10, 2, key="dr_w_luck")
    with col3:
        w_consistency = st.slider("Consistency weight", 0, 10, 1, key="dr_w_consist")
        w_playoff = st.slider("Playoff appearances weight", 0, 10, 1, key="dr_w_playoff")

    total_weight = w_wins + w_pf + w_allplay + w_luck + w_consistency + w_playoff
    if total_weight == 0:
        st.warning("All weights are 0 — set at least one above 0.")
        return

    st.divider()

    with st.spinner("Computing rankings…"):
        rankings = _compute_composite(view_df, matchups_df, lid, w_wins, w_pf, w_allplay, w_luck, w_consistency, w_playoff)

    if rankings.empty:
        st.info("Could not compute rankings.")
        return

    high_corr = _check_correlations(rankings)
    if high_corr:
        st.warning(f"High correlation detected between: {', '.join(high_corr)}. These metrics may overlap.")

    min_seasons_filter = st.session_state.get("min_seasons_played", 1)
    if min_seasons_filter > 1 and "Seasons" in rankings.columns:
        rankings = rankings[rankings["Seasons"] >= min_seasons_filter].reset_index(drop=True)
    rankings.insert(0, "Rank", range(1, len(rankings) + 1))

    display_cols = [c for c in [
        "Rank", "Manager", "Composite Score",
        "Win%", "Points For", "All-Play%", "Expected Wins", "Consistency", "Playoff Apps",
        "Seasons"
    ] if c in rankings.columns]

    styled = rankings[display_cols].copy()
    for col in ["Win%", "All-Play%"]:
        if col in styled.columns:
            styled[col] = styled[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
    for col in ["Points For", "Expected Wins", "Composite Score"]:
        if col in styled.columns:
            styled[col] = styled[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")

    st.dataframe(styled, use_container_width=True, hide_index=True)

    fig = px.bar(
        rankings.head(15).sort_values("Composite Score"),
        x="Composite Score",
        y="Manager",
        orientation="h",
        color="Composite Score",
        color_continuous_scale=["#E53E3E", "#F7C59F", "#38A169"],
        labels={"Composite Score": "Score"},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        coloraxis_showscale=False,
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("How scores are computed"):
        st.markdown(f"""
Each metric is **normalized to 0–1** (min-max), then multiplied by its weight, then summed.

| Metric | Weight | Description |
|---|---|---|
| Win% | {w_wins} | H2H wins / total games |
| Points For | {w_pf} | Total fantasy points scored |
| All-Play% | {w_allplay} | Weekly win rate vs all opponents |
| Expected Wins | {w_luck} | Average simulated wins across all schedules |
| Consistency | {w_consistency} | Inverse of weekly score std deviation |
| Playoff Apps | {w_playoff} | Seasons with playoff appearance |

**Note:** Highly correlated metrics (Win% and All-Play%) effectively double-count similar information.
        """)


def _compute_composite(
    view_df: pd.DataFrame,
    full_df: pd.DataFrame,
    lid: str | None,
    w_wins: int,
    w_pf: int,
    w_allplay: int,
    w_luck: int,
    w_consistency: int,
    w_playoff: int,
) -> pd.DataFrame:
    career = career_standings(view_df, league_id=lid)
    if career.empty:
        return pd.DataFrame()

    metrics = career[["owner"]].copy().rename(columns={"owner": "Manager"})

    if "h2h_win_pct" in career.columns:
        metrics["Win%"] = career["h2h_win_pct"].fillna(0)
    else:
        metrics["Win%"] = 0.0

    if "points_for" in career.columns:
        metrics["Points For"] = career["points_for"].fillna(0)
    else:
        metrics["Points For"] = 0.0

    if "seasons_played" in career.columns:
        metrics["Seasons"] = career["seasons_played"].fillna(1)
    else:
        metrics["Seasons"] = 1

    # All-play: for each team-week, count wins vs all other teams that week
    all_scores = []
    for _, row in view_df.iterrows():
        all_scores.append({"owner": row["team_a_owner"], "week": row["week"], "season": row["season"], "pts": row["points_a"]})
        all_scores.append({"owner": row["team_b_owner"], "week": row["week"], "season": row["season"], "pts": row["points_b"]})
    scores_df = pd.DataFrame(all_scores).dropna(subset=["pts"])

    allplay: dict[str, float] = {}
    for (season, week), grp in scores_df.groupby(["season", "week"]):
        sorted_pts = grp["pts"].values
        for _, srow in grp.iterrows():
            owner = srow["owner"]
            pts = srow["pts"]
            wins_this_week = int((sorted_pts < pts).sum())
            total_possible = len(sorted_pts) - 1
            if total_possible > 0:
                allplay[owner] = allplay.get(owner, 0) + wins_this_week / total_possible

    total_weeks = scores_df.groupby("owner").size().to_dict()
    ap_pct = {o: (allplay.get(o, 0) / max(1, total_weeks.get(o, 1))) for o in metrics["Manager"]}
    metrics["All-Play%"] = metrics["Manager"].map(ap_pct).fillna(0)

    # Expected wins from luck analysis (across all seasons in view)
    seasons_in_view = view_df["season"].unique()
    exp_wins: dict[str, float] = {}
    for season in seasons_in_view:
        try:
            luck = luck_metrics(view_df, int(season), lid)
            if not luck.empty and "expected_wins" in luck.columns:
                for _, lrow in luck.iterrows():
                    exp_wins[lrow["owner"]] = exp_wins.get(lrow["owner"], 0) + lrow["expected_wins"]
        except Exception:
            pass
    metrics["Expected Wins"] = metrics["Manager"].map(exp_wins).fillna(0)

    # Consistency: inverse std dev of weekly scores
    std_scores = scores_df.groupby("owner")["pts"].std().to_dict()
    max_std = max(std_scores.values()) if std_scores else 1
    metrics["Consistency"] = metrics["Manager"].map(
        lambda o: max(0, 1 - (std_scores.get(o, 0) / max(max_std, 1)))
    )

    # Playoff appearances
    playoff_df = full_df[full_df["is_playoff"].fillna(False) | full_df["is_championship"].fillna(False)]
    playoff_owners: dict[str, int] = {}
    for _, row in playoff_df.iterrows():
        for owner in [row["team_a_owner"], row["team_b_owner"]]:
            if owner:
                playoff_owners[owner] = playoff_owners.get(owner, 0)
    # Count distinct seasons in playoffs per owner
    if not playoff_df.empty:
        pa = (
            pd.concat([
                playoff_df[["team_a_owner", "season"]].rename(columns={"team_a_owner": "owner"}),
                playoff_df[["team_b_owner", "season"]].rename(columns={"team_b_owner": "owner"}),
            ])
            .dropna(subset=["owner"])
            .groupby("owner")["season"]
            .nunique()
            .to_dict()
        )
    else:
        pa = {}
    metrics["Playoff Apps"] = metrics["Manager"].map(pa).fillna(0)

    # Normalize and compute composite
    metric_cols = []
    weight_map = {
        "Win%": w_wins,
        "Points For": w_pf,
        "All-Play%": w_allplay,
        "Expected Wins": w_luck,
        "Consistency": w_consistency,
        "Playoff Apps": w_playoff,
    }

    score = pd.Series(0.0, index=metrics.index)
    total_w = sum(weight_map.values())
    if total_w == 0:
        return pd.DataFrame()

    for col, weight in weight_map.items():
        if col not in metrics.columns or weight == 0:
            continue
        col_min = metrics[col].min()
        col_max = metrics[col].max()
        if col_max == col_min:
            normalized = pd.Series(0.5, index=metrics.index)
        else:
            normalized = (metrics[col] - col_min) / (col_max - col_min)
        score += normalized * (weight / total_w)
        metric_cols.append(col)

    metrics["Composite Score"] = (score * 100).round(1)
    return metrics.sort_values("Composite Score", ascending=False).reset_index(drop=True)


def _check_correlations(rankings: pd.DataFrame) -> list[str]:
    corr_pairs = []
    check = [(c1, c2) for c1 in ["Win%", "All-Play%", "Expected Wins"] for c2 in ["Win%", "All-Play%", "Expected Wins"] if c1 < c2]
    for c1, c2 in check:
        if c1 in rankings.columns and c2 in rankings.columns:
            try:
                r = rankings[c1].corr(rankings[c2])
                if abs(r) > 0.85:
                    corr_pairs.append(f"{c1} ↔ {c2} (r={r:.2f})")
            except Exception:
                pass
    return corr_pairs
