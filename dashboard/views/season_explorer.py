"""Season explorer page: full drill-down for any single season."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import season_standings
from utils import apply_league_filter, filter_offensive_rosters, season_has_idp

_known_seasons = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]


def render(conn) -> None:
    """Render the Season Explorer page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📈 Season Explorer")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    seasons_df = apply_league_filter(conn.execute("SELECT * FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks ORDER BY overall").df())
    roster_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())

    available = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    num_teams_map = dict(zip(seasons_df["season"], seasons_df["num_teams"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in available]

    selected_label = st.selectbox("Season", season_labels, index=len(available) - 1)
    selected_season = available[season_labels.index(selected_label)]

    season_matchups = matchups_df[matchups_df["season"] == selected_season].copy()
    season_draft = draft_df[draft_df["season"] == selected_season].copy()
    season_roster = roster_df[roster_df["season"] == selected_season].copy()
    provider = provider_map.get(selected_season, "unknown")
    num_teams = num_teams_map.get(selected_season, "?")

    # IDP toggle — only shown when season has defensive players
    has_idp = season_has_idp(season_roster, selected_season)
    exclude_def = False
    if has_idp:
        exclude_def = st.checkbox(
            "Exclude defensive players from scoring (IDP season)",
            value=True,
            help="This season used Individual Defensive Players (IDP). "
                 "Excluding them makes scores comparable to later offensive-only seasons.",
        )

    # --- Section 1: Season Summary ---
    st.subheader("Season Summary")
    champ_row = season_matchups[season_matchups["is_championship"] == True]
    champion = runner_up = "N/A"
    if not champ_row.empty:
        r = champ_row.iloc[0]
        if r["winner_team_id"] == r["team_a_id"]:
            champion, runner_up = r["team_a_owner"], r["team_b_owner"]
        else:
            champion, runner_up = r["team_b_owner"], r["team_a_owner"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Season", str(selected_season))
    c2.metric("Teams", str(num_teams))
    c3.metric("Champion", champion)
    c4.metric("Runner-Up", runner_up)
    st.caption(f"Platform: {provider.upper()}")
    st.divider()

    # --- Section 2: Final Standings ---
    st.subheader("Final Standings")
    standings = season_standings(season_matchups, selected_season)
    if standings.empty:
        st.info("No standings data available.")
    else:
        standings.insert(0, "Rank", range(1, len(standings) + 1))
        display_cols = ["Rank", "owner", "total_wins", "total_losses", "h2h_ties", "total_win_pct", "points_for", "points_against"]
        rename = {
            "owner": "Owner", "total_wins": "W", "total_losses": "L", "h2h_ties": "T",
            "total_win_pct": "Win%", "points_for": "PF", "points_against": "PA",
        }
        out = standings[display_cols].rename(columns=rename)
        out["Win%"] = out["Win%"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
        out["PF"] = out["PF"].round(2)
        out["PA"] = out["PA"].round(2)
        st.dataframe(out, use_container_width=True, hide_index=True)
    st.divider()

    # --- Section 3: Weekly Scores Heatmap ---
    st.subheader("Weekly Scores Heatmap")
    reg = season_matchups[~season_matchups["is_playoff"] & ~season_matchups["is_consolation"]].copy()
    reg["week"] = pd.to_numeric(reg["week"], errors="coerce")
    reg = reg.dropna(subset=["week"])
    reg["week"] = reg["week"].astype(int)

    if not reg.empty:
        if exclude_def and not season_roster.empty:
            # Recalculate team scores from offensive starters only
            off_roster = filter_offensive_rosters(
                season_roster[(season_roster["starter"] == True) & (season_roster["season"] == selected_season)]
            )
            weekly_totals = (
                off_roster.groupby(["week", "owner_name"])["points"]
                .sum()
                .reset_index(name="pts")
                .rename(columns={"owner_name": "owner"})
            )
            weekly_totals["week"] = pd.to_numeric(weekly_totals["week"], errors="coerce").dropna().astype(int)
            all_scores = weekly_totals.dropna(subset=["pts"])
            if has_idp:
                st.caption("⚠️ Scores recalculated from offensive starters only (QB/RB/WR/TE/K). Defensive player scores excluded.")
        else:
            rows_a = reg[["week", "team_a_owner", "points_a"]].rename(
                columns={"team_a_owner": "owner", "points_a": "pts"}
            )
            rows_b = reg[["week", "team_b_owner", "points_b"]].rename(
                columns={"team_b_owner": "owner", "points_b": "pts"}
            )
            all_scores = pd.concat([rows_a, rows_b]).dropna(subset=["pts"])
        pivot = all_scores.pivot_table(index="owner", columns="week", values="pts", aggfunc="mean")
        fig = px.imshow(
            pivot,
            labels={"x": "Week", "y": "Manager", "color": "Points"},
            color_continuous_scale="RdYlGn",
            aspect="auto",
        )
        fig.update_layout(title=f"{selected_season} Weekly Score Heatmap")
        st.plotly_chart(fig, use_container_width=True)

        # --- Section 4: Score Distribution ---
        st.subheader("Score Distribution")
        fig2 = px.box(
            all_scores, x="owner", y="pts",
            labels={"owner": "Manager", "pts": "Weekly Points"},
            color="owner",
        )
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No regular-season score data available.")

    st.divider()

    # --- Section 5: All Matchups ---
    st.subheader("All Matchups")
    if not season_matchups.empty:
        m = season_matchups.copy()
        m["week"] = pd.to_numeric(m["week"], errors="coerce").fillna(0).astype(int)
        m["winner"] = m.apply(
            lambda r: r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"], axis=1
        )
        m["type"] = m.apply(
            lambda r: "🏆 Champ" if r["is_championship"] else
                      ("🎯 Playoff" if r["is_playoff"] else
                       ("🥈 Consolation" if r["is_consolation"] else "Regular")),
            axis=1,
        )
        m["score"] = m.apply(
            lambda r: f"{r['points_a']:.2f} – {r['points_b']:.2f}"
            if pd.notna(r["points_a"]) else "N/A", axis=1
        )
        matchup_display = m[["week", "type", "team_a_owner", "score", "team_b_owner", "winner"]].rename(columns={
            "week": "Wk", "type": "Type", "team_a_owner": "Team A",
            "score": "Score", "team_b_owner": "Team B", "winner": "Winner",
        })
        st.dataframe(matchup_display, use_container_width=True, hide_index=True)
    st.divider()

    # --- Section 6: Draft Summary ---
    st.subheader("Draft Summary (Rounds 1–5)")
    if season_draft.empty:
        st.info("No draft data available for this season.")
    else:
        early = season_draft[season_draft["round"] <= 5].copy()
        draft_display = early[["overall", "round", "owner_name", "player", "position", "keeper"]].rename(columns={
            "overall": "Pick", "round": "Rd", "owner_name": "Owner",
            "player": "Player", "position": "Pos", "keeper": "Keeper",
        })
        st.dataframe(draft_display, use_container_width=True, hide_index=True)
