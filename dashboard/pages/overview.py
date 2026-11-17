"""League overview page: champions, season summaries, scoring trends."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


def render(conn) -> None:
    """Render the League Overview page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏠 League Overview")

    seasons_df = conn.execute("SELECT * FROM seasons ORDER BY season").df()
    matchups_df = conn.execute("SELECT * FROM matchups").df()

    # Champions
    st.subheader("🏆 Champions")
    champs = conn.execute("""
        SELECT season, team_a_name AS champion, team_a_owner AS champion_owner,
               team_b_name AS runner_up, team_b_owner AS runner_up_owner,
               ROUND(points_a, 2) AS champion_pts, ROUND(points_b, 2) AS runner_up_pts,
               ROUND(points_a - points_b, 2) AS margin
        FROM matchups
        WHERE is_championship = TRUE
        ORDER BY season
    """).df()
    if not champs.empty:
        st.dataframe(champs, use_container_width=True, hide_index=True)
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
    st.caption("⚠️ Note: 2021 season data is currently missing from this export.")
