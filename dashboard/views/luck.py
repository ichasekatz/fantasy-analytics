"""Luck analysis page: expected wins vs actual, schedule difficulty."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.luck import luck_metrics
from utils import apply_league_filter


def _all_seasons_luck(matchups_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    seasons = sorted(matchups_df["season"].dropna().unique())
    frames = []
    for s in seasons:
        ldf = luck_metrics(matchups_df, int(s))
        if not ldf.empty:
            ldf["season"] = s
            frames.append(ldf)
    if not frames:
        return pd.DataFrame(), pd.Series(dtype=int)
    combined = pd.concat(frames, ignore_index=True)
    seasons_played = combined.groupby("owner")["season"].nunique()
    agg = (
        combined.groupby("owner")
        .agg(
            actual_wins=("actual_wins", "sum"),
            expected_wins=("expected_wins", "sum"),
            schedule_difficulty=("schedule_difficulty", "mean"),
        )
        .reset_index()
    )
    agg["luck_delta"] = agg["actual_wins"] - agg["expected_wins"]
    return agg.sort_values("luck_delta", ascending=False).reset_index(drop=True), seasons_played


def render(conn) -> None:
    """Render the Luck Analysis page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🍀 Luck Analysis")
    st.caption(
        "Expected wins = how many wins a team would expect if they played every other team each week. "
        "Luck delta = actual wins − expected wins. Positive = lucky schedule, negative = unlucky."
    )

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = ["All Seasons"] + [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(season_labels) - 1)
    all_seasons = selected_label == "All Seasons"

    if all_seasons:
        luck, seasons_played = _all_seasons_luck(matchups_df)
        min_seasons_filter = st.session_state.get("min_seasons_played", 1)
        if min_seasons_filter > 1 and not luck.empty:
            keep = seasons_played[seasons_played >= min_seasons_filter].index
            luck = luck[luck["owner"].isin(keep)].reset_index(drop=True)
    else:
        selected_season = seasons[season_labels.index(selected_label) - 1]
        luck = luck_metrics(matchups_df, selected_season)

    if luck.empty:
        st.info("No luck data available.")
        return

    # Table
    st.subheader("Expected vs Actual Wins")
    display = luck.copy()
    display["expected_wins"] = display["expected_wins"].round(2)
    display["luck_delta"] = display["luck_delta"].round(2)
    display["schedule_difficulty"] = display["schedule_difficulty"].round(1)
    rename = {
        "owner": "Owner",
        "actual_wins": "Actual W", "expected_wins": "Expected W",
        "luck_delta": "Luck Δ", "schedule_difficulty": "Opp Avg PF",
    }
    if not all_seasons:
        rename["team"] = "Team"
    display = display.rename(columns=rename)
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.divider()

    # Bar chart
    st.subheader("Luck Delta by Manager")
    fig = px.bar(
        luck.sort_values("luck_delta"),
        x="luck_delta", y="owner", orientation="h",
        labels={"luck_delta": "Luck Δ (Actual − Expected Wins)", "owner": "Manager"},
        color="luck_delta",
        color_continuous_scale=["#d62728", "#aec7e8", "#1f77b4"],
        color_continuous_midpoint=0,
    )
    fig.update_layout(
        showlegend=False, coloraxis_showscale=False,
        height=max(350, len(luck) * 30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Schedule difficulty
    st.subheader("Schedule Difficulty (Avg Opponent Score)")
    fig2 = px.bar(
        luck.sort_values("schedule_difficulty", ascending=False),
        x="owner", y="schedule_difficulty",
        labels={"schedule_difficulty": "Avg Opponent Points", "owner": "Manager"},
        color_discrete_sequence=["#ff7f0e"],
    )
    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig2, use_container_width=True)
