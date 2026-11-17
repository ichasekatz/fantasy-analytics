"""Matchup browser page: view all matchups by season and week."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))

from utils import apply_league_filter


def render(conn) -> None:
    """Render the Matchups browser page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📅 Matchup Browser")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups ORDER BY season, week").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    col1, col2 = st.columns([2, 3])
    with col1:
        selected_label = st.selectbox("Season", season_labels)
    selected_season = seasons[season_labels.index(selected_label)]

    season_df = matchups_df[matchups_df["season"] == selected_season].copy()
    season_df["week"] = pd.to_numeric(season_df["week"], errors="coerce")
    season_df = season_df.dropna(subset=["week"])
    season_df["week"] = season_df["week"].astype(int)

    with col2:
        view = st.radio("View", ["By Week", "Full Season"], horizontal=True)

    if view == "By Week":
        weeks = sorted(season_df["week"].unique())
        selected_week = st.selectbox("Week", weeks)
        week_df = season_df[season_df["week"] == selected_week].copy()
        _display_matchup_table(week_df)
    else:
        with st.expander("Filter by type"):
            show_regular = st.checkbox("Regular Season", value=True)
            show_playoff = st.checkbox("Playoffs", value=True)
            show_consolation = st.checkbox("Consolation", value=True)
        filtered = season_df[
            (season_df["is_playoff"].map(lambda x: show_playoff if x else show_regular))
            | (season_df["is_consolation"] & show_consolation)
        ]
        _display_matchup_table(filtered)


def _display_matchup_table(df: pd.DataFrame) -> None:
    """Display a formatted matchup table.

    Args:
        df (pd.DataFrame): Filtered matchups DataFrame for display.
    """
    if df.empty:
        st.info("No matchups found.")
        return

    display = df.copy()
    display["winner"] = display.apply(
        lambda r: r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"],
        axis=1,
    )
    display["type"] = display.apply(
        lambda r: "🏆 Championship" if r["is_championship"] else
                  ("🎯 Playoff" if r["is_playoff"] else
                   ("🥈 Consolation" if r["is_consolation"] else "Regular")),
        axis=1,
    )
    display["score"] = display.apply(
        lambda r: f"{r['points_a']:.2f} – {r['points_b']:.2f}"
        if pd.notna(r["points_a"]) and pd.notna(r["points_b"]) else "N/A",
        axis=1,
    )
    cols = ["week", "type", "team_a_owner", "team_a_name", "score", "team_b_name", "team_b_owner", "winner"]
    col_labels = {
        "week": "Wk", "type": "Type",
        "team_a_owner": "Owner A", "team_a_name": "Team A",
        "score": "Score",
        "team_b_name": "Team B", "team_b_owner": "Owner B",
        "winner": "Winner",
    }
    out = display[cols].rename(columns=col_labels)
    st.dataframe(out, use_container_width=True, hide_index=True)
    st.caption(f"{len(display)} matchup(s)")
