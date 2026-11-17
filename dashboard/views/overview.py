"""League overview page: champions, season summaries, scoring trends."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))

from utils import apply_league_filter, filter_redraft, is_dynasty_league, style_dataframe


def render(conn) -> None:
    """Render the League Overview page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏠 League Overview")

    lid = st.session_state.get("selected_league_id")

    seasons_df = apply_league_filter(conn.execute("SELECT * FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    # Exclude dynasty leagues when viewing All Leagues
    if lid is None:
        seasons_df = filter_redraft(seasons_df)
        matchups_df = filter_redraft(matchups_df)

    # Champions
    st.subheader("🏆 Champions")
    champs = apply_league_filter(conn.execute("""
        SELECT league_id, season,
               CASE WHEN winner_team_id = team_a_id THEN team_a_name ELSE team_b_name END AS champion,
               CASE WHEN winner_team_id = team_a_id THEN team_a_owner ELSE team_b_owner END AS champion_owner,
               CASE WHEN winner_team_id = team_a_id THEN team_b_name ELSE team_a_name END AS runner_up,
               CASE WHEN winner_team_id = team_a_id THEN team_b_owner ELSE team_a_owner END AS runner_up_owner,
               CASE WHEN winner_team_id = team_a_id THEN ROUND(points_a, 2) ELSE ROUND(points_b, 2) END AS champion_pts,
               CASE WHEN winner_team_id = team_a_id THEN ROUND(points_b, 2) ELSE ROUND(points_a, 2) END AS runner_up_pts,
               ABS(ROUND(points_a - points_b, 2)) AS margin
        FROM matchups
        WHERE is_championship = TRUE
        ORDER BY season
    """).df())
    if lid is None and "league_id" in champs.columns:
        champs = champs[~champs["league_id"].apply(is_dynasty_league)]

    if not champs.empty:
        styled_champs = style_dataframe(champs, higher_is_better=["champion_pts", "margin"], lower_is_better=["runner_up_pts"])
        st.dataframe(styled_champs, use_container_width=True, hide_index=True)
    else:
        st.info("No championship matchup data available.")

    st.divider()

    # Season summary
    st.subheader("📅 Season Summary")
    reg = matchups_df[~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]]
    if not reg.empty:
        all_scores = pd.concat(
            [reg[["season", "points_a"]].rename(columns={"points_a": "pts"}),
             reg[["season", "points_b"]].rename(columns={"points_b": "pts"})]
        ).dropna()
        summary = all_scores.groupby("season")["pts"].agg(
            avg_score="mean", median_score="median", high_score="max", low_score="min", total_games="count"
        ).reset_index()
        summary = summary.merge(seasons_df[["season", "num_teams", "provider"]], on="season", how="left")
        summary["avg_score"] = summary["avg_score"].round(1)
        summary["median_score"] = summary["median_score"].round(1)
        summary["high_score"] = summary["high_score"].round(2)
        summary["low_score"] = summary["low_score"].round(2)
        st.dataframe(summary, use_container_width=True, hide_index=True)

        # Scoring trend chart
        st.subheader("📈 Average Score by Season")
        fig = px.line(
            summary, x="season", y="avg_score",
            markers=True, labels={"season": "Season", "avg_score": "Avg Points"},
            color_discrete_sequence=["#1f77b4"],
        )
        fig.update_layout(xaxis=dict(tickmode="array", tickvals=summary["season"].tolist()))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Current season
    latest_season = int(matchups_df["season"].max())
    st.subheader(f"📆 {latest_season} Season — Weekly Scores")
    cur = matchups_df[matchups_df["season"] == latest_season].dropna(subset=["week"])
    if not cur.empty:
        week_avgs = pd.concat(
            [cur[["week", "points_a"]].rename(columns={"points_a": "pts"}),
             cur[["week", "points_b"]].rename(columns={"points_b": "pts"})]
        ).dropna().groupby("week")["pts"].mean().reset_index()
        week_avgs["week"] = week_avgs["week"].astype(int)
        fig2 = px.bar(
            week_avgs, x="week", y="pts",
            labels={"week": "Week", "pts": "Avg Points"},
            color_discrete_sequence=["#2ca02c"],
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
