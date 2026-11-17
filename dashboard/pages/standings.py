"""Season standings page: regular-season records and all-play standings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import all_play_records, season_standings


def render(conn) -> None:
    """Render the Standings page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📊 Standings")

    matchups_df = conn.execute("SELECT * FROM matchups").df()
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(seasons) - 1)
    selected_season = seasons[season_labels.index(selected_label)]

    tab1, tab2 = st.tabs(["Regular Season Standings", "All-Play Standings"])

    with tab1:
        standings = season_standings(matchups_df, selected_season)
        if standings.empty:
            st.info("No regular-season data available.")
        else:
            standings.insert(0, "Rank", range(1, len(standings) + 1))
            display_cols = ["Rank", "owner", "team", "wins", "losses", "ties", "win_pct", "points_for", "points_against", "avg_pf"]
            rename = {
                "owner": "Owner", "team": "Team",
                "wins": "W", "losses": "L", "ties": "T",
                "win_pct": "Win%", "points_for": "PF", "points_against": "PA", "avg_pf": "Avg PF",
            }
            out = standings[display_cols].rename(columns=rename)
            out["Win%"] = out["Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
            out["PF"] = out["PF"].round(2)
            out["PA"] = out["PA"].round(2)
            out["Avg PF"] = out["Avg PF"].round(1)
            st.dataframe(out, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Standings CSV",
                out.to_csv(index=False).encode("utf-8"),
                f"standings_{selected_season}.csv", "text/csv",
                key=f"dl_standings_{selected_season}",
            )

    with tab2:
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
            st.download_button(
                "⬇️ Download All-Play CSV",
                out.to_csv(index=False).encode("utf-8"),
                f"allplay_{selected_season}.csv", "text/csv",
                key=f"dl_allplay_{selected_season}",
            )
            st.caption(
                "All-play win% = how often each team would win if they played every other team each week. "
                "Removes schedule luck."
            )
