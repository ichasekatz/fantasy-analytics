"""Power Rankings: multi-method weekly and seasonal team strength rankings."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.luck import expected_wins
from fantasy.analytics.standings import all_play_records, season_standings
from utils import apply_league_filter


def _recent_form(matchups_df: pd.DataFrame, season: int, n_weeks: int = 4) -> pd.DataFrame:
    """Average points over the last n_weeks of the regular season.

    Args:
        matchups_df: Full matchups DataFrame.
        season: Season year.
        n_weeks: Number of recent weeks to average.

    Returns:
        DataFrame with owner, recent_avg columns.
    """
    reg = matchups_df[
        (matchups_df["season"] == season)
        & (~matchups_df["is_playoff"].fillna(False))
        & (~matchups_df["is_consolation"].fillna(False))
        & (~matchups_df["is_championship"].fillna(False))
    ].copy()

    if reg.empty:
        return pd.DataFrame(columns=["owner", "recent_avg"])

    max_week = int(reg["week"].max())
    cutoff = max_week - n_weeks + 1

    recent = reg[reg["week"] >= cutoff]

    rows = []
    for _, row in recent.iterrows():
        rows.append({"owner": row["team_a_owner"], "pts": row["points_a"]})
        rows.append({"owner": row["team_b_owner"], "pts": row["points_b"]})

    if not rows:
        return pd.DataFrame(columns=["owner", "recent_avg"])

    df = pd.DataFrame(rows).dropna()
    return df.groupby("owner")["pts"].mean().reset_index().rename(columns={"pts": "recent_avg"})


def _rank_col(series: pd.Series, ascending: bool = False) -> pd.Series:
    """Rank a series (1 = best). ascending=True means lower value = better rank."""
    return series.rank(ascending=ascending, method="min").astype(int)


def _composite_rank(rank_df: pd.DataFrame, rank_cols: list[str]) -> pd.Series:
    """Average rank across methods; lower = better composite rank."""
    avg = rank_df[rank_cols].mean(axis=1)
    return avg.rank(ascending=True, method="min").astype(int)


def render(conn) -> None:
    """Render the Power Rankings page."""
    st.title("📡 Power Rankings")
    st.caption("Multi-method team strength rankings combining points, all-play, expected wins, and recent form.")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    seasons = sorted(matchups_df["season"].dropna().unique(), reverse=True)
    selected_season = st.selectbox("Season", seasons, index=0)

    tab_current, tab_history = st.tabs(["Season Rankings", "Weekly Trajectory"])

    with tab_current:
        _render_season_rankings(matchups_df, selected_season)

    with tab_history:
        _render_weekly_trajectory(matchups_df, selected_season)


def _render_season_rankings(matchups_df: pd.DataFrame, season: int) -> None:
    standings = season_standings(matchups_df, season)
    ap = all_play_records(matchups_df, season)
    exp = expected_wins(matchups_df, season)
    form = _recent_form(matchups_df, season)

    if standings.empty:
        st.info(f"No standings data for {season}.")
        return

    # Build unified table keyed on owner
    df = standings[["owner", "points_for", "avg_pf", "h2h_wins", "total_win_pct"]].copy()

    if not ap.empty:
        df = df.merge(ap[["owner", "ap_win_pct"]], on="owner", how="left")
    else:
        df["ap_win_pct"] = float("nan")

    if not exp.empty:
        df = df.merge(exp[["owner", "expected_wins"]], on="owner", how="left")
    else:
        df["expected_wins"] = float("nan")

    if not form.empty:
        df = df.merge(form, on="owner", how="left")
    else:
        df["recent_avg"] = float("nan")

    # Compute per-method ranks (1 = best)
    df["rank_pts"] = _rank_col(df["points_for"], ascending=False)
    df["rank_ap"] = _rank_col(df["ap_win_pct"].fillna(0), ascending=False)
    df["rank_xw"] = _rank_col(df["expected_wins"].fillna(0), ascending=False)
    df["rank_form"] = _rank_col(df["recent_avg"].fillna(0), ascending=False)
    rank_cols = ["rank_pts", "rank_ap", "rank_xw", "rank_form"]
    df["composite_rank"] = _composite_rank(df, rank_cols)

    df = df.sort_values("composite_rank")

    # Display table
    st.subheader(f"{season} Power Rankings")

    display = df[["owner", "composite_rank", "rank_pts", "rank_ap", "rank_xw", "rank_form",
                  "points_for", "ap_win_pct", "expected_wins", "recent_avg"]].copy()
    display = display.rename(columns={
        "owner": "Manager",
        "composite_rank": "🏅 Rank",
        "rank_pts": "Pts Rank",
        "rank_ap": "All-Play Rank",
        "rank_xw": "xWins Rank",
        "rank_form": "Form Rank",
        "points_for": "Total PF",
        "ap_win_pct": "All-Play %",
        "expected_wins": "Exp Wins",
        "recent_avg": "Recent Avg (4wk)",
    })
    display["Total PF"] = display["Total PF"].round(1)
    display["All-Play %"] = display["All-Play %"].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "—")
    display["Exp Wins"] = display["Exp Wins"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
    display["Recent Avg (4wk)"] = display["Recent Avg (4wk)"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")

    st.dataframe(display, use_container_width=True, hide_index=True)

    st.divider()

    # Bar chart: composite score (inverted so lower rank = taller bar)
    n = len(df)
    df["composite_score"] = n + 1 - df["composite_rank"]
    fig = px.bar(
        df.sort_values("composite_score", ascending=True),
        x="composite_score",
        y="owner",
        orientation="h",
        color="composite_score",
        color_continuous_scale="Blues",
        labels={"composite_score": "Composite Score", "owner": "Manager"},
        title="Composite Power Score (higher = stronger)",
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        coloraxis_showscale=False,
        height=max(300, 35 * n),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Method Definitions")
    st.markdown(
        "| Method | Definition |\n"
        "|---|---|\n"
        "| **Points** | Total fantasy points scored (raw) |\n"
        "| **All-Play %** | Win% if played every other team each week |\n"
        "| **Exp Wins** | Expected wins based on weekly score distribution |\n"
        "| **Form (4wk)** | Average points over last 4 regular-season weeks |\n"
        "| **Composite** | Average rank across all 4 methods |\n"
    )


def _render_weekly_trajectory(matchups_df: pd.DataFrame, season: int) -> None:
    """Show weekly rolling points-based power ranking trajectory."""
    st.subheader("Weekly Scoring Trajectory")
    st.caption("Average points per week through the season — a proxy for weekly power ranking movement.")

    reg = matchups_df[
        (matchups_df["season"] == season)
        & (~matchups_df["is_playoff"].fillna(False))
        & (~matchups_df["is_consolation"].fillna(False))
        & (~matchups_df["is_championship"].fillna(False))
    ].dropna(subset=["week", "points_a", "points_b"])

    if reg.empty:
        st.info("No regular-season data available.")
        return

    rows = []
    for _, row in reg.iterrows():
        rows.append({"week": int(row["week"]), "owner": row["team_a_owner"], "pts": row["points_a"]})
        rows.append({"week": int(row["week"]), "owner": row["team_b_owner"], "pts": row["points_b"]})

    scores = pd.DataFrame(rows).dropna()

    # Cumulative average through each week
    scores = scores.sort_values("week")
    scores["cumulative_avg"] = scores.groupby("owner")["pts"].expanding().mean().reset_index(level=0, drop=True)

    fig = px.line(
        scores,
        x="week",
        y="cumulative_avg",
        color="owner",
        markers=True,
        labels={"week": "Week", "cumulative_avg": "Cumulative Avg PF", "owner": "Manager"},
        title=f"{season} Season-to-Date Scoring Average",
    )
    fig.update_layout(xaxis=dict(tickmode="linear", dtick=1))
    st.plotly_chart(fig, use_container_width=True)
