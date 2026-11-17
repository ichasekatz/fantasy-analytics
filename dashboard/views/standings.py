"""Season standings page: regular-season records and all-play standings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import all_play_records, career_standings, season_standings
from utils import apply_league_filter


def render(conn) -> None:
    """Render the Standings page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📊 Standings")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    lid = st.session_state.get("selected_league_id")

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = ["All Time"] + [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(season_labels) - 1)
    all_time = selected_label == "All Time"
    selected_season = None if all_time else seasons[season_labels.index(selected_label) - 1]

    tab1, tab2 = st.tabs(["Regular Season Standings", "All-Play Standings"])

    with tab1:
        if all_time:
            career = career_standings(matchups_df, league_id=lid)
            if career.empty:
                st.info("No career data available.")
            else:
                career.insert(0, "Rank", range(1, len(career) + 1))
                display_cols = ["Rank", "owner", "h2h_wins", "h2h_losses", "h2h_ties", "h2h_win_pct", "total_wins", "points_for", "points_against", "avg_pf", "seasons_played"]
                rename = {
                    "owner": "Owner",
                    "h2h_wins": "H2H W", "h2h_losses": "H2H L", "h2h_ties": "T",
                    "h2h_win_pct": "H2H Win%", "total_wins": "Total W (inc. median)",
                    "points_for": "PF", "points_against": "PA", "avg_pf": "Avg PF",
                    "seasons_played": "Seasons",
                }
                out = career[[c for c in display_cols if c in career.columns]].rename(columns=rename)
                out["H2H Win%"] = out["H2H Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                out["PF"] = out["PF"].round(1)
                out["PA"] = out["PA"].round(1)
                out["Avg PF"] = out["Avg PF"].round(1)
                st.dataframe(out, use_container_width=True, hide_index=True)
                st.caption("H2H Win% excludes median matchup games for fair cross-season comparison.")
        else:
            standings = season_standings(matchups_df, selected_season)
            if standings.empty:
                st.info("No regular-season data available.")
            else:
                standings.insert(0, "Rank", range(1, len(standings) + 1))
                display_cols = ["Rank", "owner", "team", "total_wins", "total_losses", "h2h_ties", "total_win_pct", "points_for", "points_against", "avg_pf"]
                rename = {
                    "owner": "Owner", "team": "Team",
                    "total_wins": "W", "total_losses": "L", "h2h_ties": "T",
                    "total_win_pct": "Win%", "points_for": "PF", "points_against": "PA", "avg_pf": "Avg PF",
                }
                out = standings[display_cols].rename(columns=rename)
                out["Win%"] = out["Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                out["PF"] = out["PF"].round(2)
                out["PA"] = out["PA"].round(2)
                out["Avg PF"] = out["Avg PF"].round(1)
                st.dataframe(out, use_container_width=True, hide_index=True)

    with tab2:
        if all_time:
            st.info("All-play standings are per-season. Select a season to view.")
        else:
            ap = all_play_records(matchups_df, selected_season)
            if ap.empty:
                st.info("No all-play data available.")
            else:
                ap.insert(0, "Rank", range(1, len(ap) + 1))
                display_cols = ["Rank", "owner", "team", "ap_wins", "ap_losses", "ap_ties", "ap_win_pct"]
                rename = {
                    "owner": "Owner", "team": "Team",
                    "ap_wins": "AP W", "ap_losses": "AP L", "ap_ties": "AP T", "ap_win_pct": "AP Win%",
                }
                out = ap[display_cols].rename(columns=rename)
                out["AP Win%"] = out["AP Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                st.dataframe(out, use_container_width=True, hide_index=True)
                st.caption(
                    "All-play win% = how often each team would win if they played every other team each week. "
                    "Removes schedule luck."
                )
