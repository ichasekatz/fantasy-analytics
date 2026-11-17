"""Playoff Odds: historical analysis and Monte Carlo simulation."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.simulations import _infer_playoff_cutoff, monte_carlo_standings
from style import inject_css
from utils import apply_league_filter


def _all_play_pct(matchups_df: pd.DataFrame, season: int, league_id: str | None) -> pd.DataFrame:
    df = matchups_df[matchups_df["season"] == season].copy()
    if league_id:
        df = df[df["league_id"] == league_id]
    reg = df[~df["is_playoff"].fillna(False) & ~df["is_consolation"].fillna(False) & ~df["is_championship"].fillna(False)]

    scores: dict[str, dict[int, float]] = {}
    for _, row in reg.iterrows():
        week = int(row["week"])
        scores.setdefault(row["team_a_owner"], {})[week] = float(row["points_a"])
        scores.setdefault(row["team_b_owner"], {})[week] = float(row["points_b"])

    owners = list(scores.keys())
    if len(owners) < 2:
        return pd.DataFrame()

    weeks = sorted({w for s in scores.values() for w in s})
    n_teams = len(owners)

    expected: dict[str, float] = {o: 0.0 for o in owners}
    actual_wins: dict[str, int] = {o: 0 for o in owners}

    for week in weeks:
        week_scores = [(o, scores.get(o, {}).get(week, 0.0)) for o in owners]
        for o, s in week_scores:
            beaten = sum(1 for other_o, other_s in week_scores if other_o != o and s > other_s)
            expected[o] += beaten / (n_teams - 1)

    for _, row in reg.iterrows():
        pa, pb = row["points_a"], row["points_b"]
        if pa > pb:
            actual_wins[row["team_a_owner"]] = actual_wins.get(row["team_a_owner"], 0) + 1
        elif pb > pa:
            actual_wins[row["team_b_owner"]] = actual_wins.get(row["team_b_owner"], 0) + 1

    # Playoff appearance
    playoff_rows = df[df["is_playoff"].fillna(False)]
    playoff_owners = set(playoff_rows["team_a_owner"].tolist()) | set(playoff_rows["team_b_owner"].tolist())

    rows = []
    for o in owners:
        all_play = expected[o]
        total_possible = len(weeks) * (n_teams - 1) / (n_teams - 1)
        all_play_pct_val = all_play / len(weeks) if weeks else 0.0
        rows.append({
            "owner": o,
            "season": season,
            "actual_wins": actual_wins.get(o, 0),
            "all_play_wins": round(all_play, 2),
            "all_play_pct": round(all_play_pct_val, 3),
            "made_playoffs": o in playoff_owners,
        })

    result = pd.DataFrame(rows).sort_values("all_play_pct", ascending=False).reset_index(drop=True)
    result["ap_rank"] = range(1, len(result) + 1)
    cutoff = _infer_playoff_cutoff(matchups_df, season)
    result["expected_playoff"] = result["ap_rank"] <= cutoff
    result["deserved"] = result["made_playoffs"] == result["expected_playoff"]
    return result


def render(conn) -> None:
    st.title("🎲 Playoff Odds")
    inject_css()

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    lid: str | None = st.session_state.get("selected_league_id")

    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    seasons = sorted(matchups_df["season"].dropna().unique(), reverse=True)

    tab1, tab2 = st.tabs(["Historical Analysis", "Season Simulation"])

    with tab1:
        _render_historical(matchups_df, seasons, lid)

    with tab2:
        _render_simulation(matchups_df, seasons, lid)


def _render_historical(matchups_df: pd.DataFrame, seasons: list, lid: str | None) -> None:
    st.subheader("Historical Playoff Fairness")
    st.caption("Did the right teams make the playoffs? All-play rank = where you'd finish if you played everyone each week.")

    all_rows = []
    for s in seasons:
        df_s = _all_play_pct(matchups_df, int(s), lid)
        if not df_s.empty:
            all_rows.append(df_s)

    if not all_rows:
        st.info("No data available.")
        return

    combined = pd.concat(all_rows, ignore_index=True)

    seasons_sel = st.multiselect("Seasons", options=[str(s) for s in seasons], default=[str(seasons[0])], key="po_hist_seasons")
    if seasons_sel:
        combined = combined[combined["season"].isin([int(s) for s in seasons_sel])]

    display = combined[["season", "owner", "actual_wins", "all_play_wins", "all_play_pct", "made_playoffs", "deserved"]].rename(columns={
        "season": "Season",
        "owner": "Manager",
        "actual_wins": "H2H Wins",
        "all_play_wins": "All-Play Wins",
        "all_play_pct": "All-Play %",
        "made_playoffs": "Made Playoffs",
        "deserved": "Deserved?",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    if len(seasons_sel) == 1:
        season_int = int(seasons_sel[0])
        season_df = combined[combined["season"] == season_int]
        fig = px.scatter(
            season_df,
            x="all_play_pct",
            y="actual_wins",
            color="made_playoffs",
            text="owner",
            color_discrete_map={True: "#38A169", False: "#E53E3E"},
            labels={"all_play_pct": "All-Play Win %", "actual_wins": "H2H Wins", "made_playoffs": "Made Playoffs"},
        )
        fig.update_traces(textposition="top center", marker_size=12)
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # Only show snubs/lucky for seasons that actually have playoff data
    seasons_with_playoffs = combined.groupby("season")["made_playoffs"].any()
    finished_seasons = seasons_with_playoffs[seasons_with_playoffs].index
    finished = combined[combined["season"].isin(finished_seasons)]

    snubs = finished[(finished["made_playoffs"] == False) & (~finished["deserved"])]
    lucky_in = finished[(finished["made_playoffs"] == True) & (~finished["deserved"])]

    if not snubs.empty:
        st.error(f"Snubbed teams (should've made playoffs): {', '.join(snubs['owner'].unique())}")
    if not lucky_in.empty:
        st.warning(f"Lucky playoff entries (all-play rank said no): {', '.join(lucky_in['owner'].unique())}")


def _render_simulation(matchups_df: pd.DataFrame, seasons: list, lid: str | None) -> None:
    st.subheader("Monte Carlo Playoff Probability")
    st.caption("Simulates 1,000 alternate schedules. P(playoffs) = fraction where you'd rank in top-N by wins.")

    sel = st.selectbox("Season", [str(s) for s in seasons], key="po_sim_season")
    season = int(sel)

    n_sims = st.slider("Simulations", 200, 2000, 500, step=100, key="po_n_sims")

    with st.spinner(f"Running {n_sims} schedule simulations…"):
        mc = monte_carlo_standings(matchups_df, season, n_sims=n_sims, league_id=lid)

    if mc.empty:
        st.info("Not enough data for this season.")
        return

    # Actual playoff appearances
    playoff_rows = matchups_df[(matchups_df["season"] == season) & matchups_df["is_playoff"].fillna(False)]
    playoff_owners = set(playoff_rows["team_a_owner"].tolist()) | set(playoff_rows["team_b_owner"].tolist())

    mc["actual_made_playoffs"] = mc["owner"].isin(playoff_owners)
    mc["playoff_pct"] = (mc["playoff_probability"] * 100).round(1)
    mc["verdict"] = mc.apply(
        lambda r: "✅ Deserved" if r["actual_made_playoffs"] and r["playoff_probability"] >= 0.5
        else ("😮 Lucky" if r["actual_made_playoffs"] and r["playoff_probability"] < 0.5
              else ("💔 Snubbed" if not r["actual_made_playoffs"] and r["playoff_probability"] >= 0.5
                    else "✗ Missed")),
        axis=1,
    )

    display = mc[["owner", "actual_wins", "mean_simulated_wins", "playoff_pct", "actual_made_playoffs", "verdict"]].rename(columns={
        "owner": "Manager",
        "actual_wins": "Actual W",
        "mean_simulated_wins": "Avg Sim W",
        "playoff_pct": "P(Playoffs) %",
        "actual_made_playoffs": "Made?",
        "verdict": "Verdict",
    })
    display["Avg Sim W"] = display["Avg Sim W"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

    fig = px.bar(
        mc.sort_values("playoff_probability", ascending=True),
        x="playoff_pct",
        y="owner",
        orientation="h",
        color="actual_made_playoffs",
        color_discrete_map={True: "#38A169", False: "#718096"},
        labels={"playoff_pct": "Simulated Playoff Probability %", "owner": "Manager", "actual_made_playoffs": "Actually Made It"},
    )
    fig.add_vline(x=50, line_dash="dash", line_color="#FF6B35", annotation_text="50% threshold")
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    season_has_playoffs = len(playoff_owners) > 0
    if season_has_playoffs:
        snubbed = mc[(mc["actual_made_playoffs"] == False) & (mc["playoff_probability"] >= 0.5)]
        lucky = mc[(mc["actual_made_playoffs"] == True) & (mc["playoff_probability"] < 0.5)]
        if not snubbed.empty:
            st.error(f"💔 Statistically deserved playoffs but missed: {', '.join(snubbed['owner'].tolist())}")
        if not lucky.empty:
            st.warning(f"😮 Made playoffs despite <50% simulated odds: {', '.join(lucky['owner'].tolist())}")
    else:
        st.info("Season still in progress — playoff verdicts available after playoffs begin.")
