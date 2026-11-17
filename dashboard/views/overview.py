"""League overview page: champions, season summaries, scoring trends."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))

from utils import apply_league_filter, rebuild_matchups_offensive, style_dataframe


def render(conn) -> None:
    """Render the League Overview page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏠 League Overview")

    seasons_df = apply_league_filter(conn.execute("SELECT * FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    # Apply IDP adjustment so champion_pts reflect offensive-only scores when excluded
    matchups_df = rebuild_matchups_offensive(matchups_df, rosters_df)

    # Champions — derived from (possibly IDP-adjusted) matchups_df
    st.subheader("🏆 Champions")
    champ_rows = matchups_df[matchups_df["is_championship"].fillna(False)].copy()
    if not champ_rows.empty:
        champ_rows["champion"] = champ_rows.apply(
            lambda r: r["team_a_name"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_name"], axis=1)
        champ_rows["champion_owner"] = champ_rows.apply(
            lambda r: r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"], axis=1)
        champ_rows["runner_up"] = champ_rows.apply(
            lambda r: r["team_b_name"] if r["winner_team_id"] == r["team_a_id"] else r["team_a_name"], axis=1)
        champ_rows["runner_up_owner"] = champ_rows.apply(
            lambda r: r["team_b_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_a_owner"], axis=1)
        champ_rows["champion_pts"] = champ_rows.apply(
            lambda r: round(float(r["points_a"]), 2) if r["winner_team_id"] == r["team_a_id"] else round(float(r["points_b"]), 2), axis=1)
        champ_rows["runner_up_pts"] = champ_rows.apply(
            lambda r: round(float(r["points_b"]), 2) if r["winner_team_id"] == r["team_a_id"] else round(float(r["points_a"]), 2), axis=1)
        champ_rows["margin"] = (champ_rows["champion_pts"] - champ_rows["runner_up_pts"]).abs().round(2)
        champs = champ_rows[["season", "champion", "champion_owner", "runner_up", "runner_up_owner",
                              "champion_pts", "runner_up_pts", "margin"]].sort_values("season").reset_index(drop=True)
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
        styled_summary = style_dataframe(
            summary,
            higher_is_better=["avg_score", "median_score", "high_score", "total_games", "num_teams"],
            lower_is_better=["low_score"],
        )
        st.dataframe(styled_summary, use_container_width=True, hide_index=True)

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
