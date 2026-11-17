"""Player Stats — weekly roster scores and matchup history."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from utils import apply_league_filter, filter_offensive_rosters, season_has_idp, style_dataframe


def render(conn) -> None:
    st.title("🏈 Player Stats")

    roster_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups ORDER BY season, week").df())

    if roster_df.empty and matchups_df.empty:
        st.info("No player data available.")
        return

    seasons = sorted(matchups_df["season"].dropna().unique(), reverse=True)
    all_owners = sorted(set(
        matchups_df["team_a_owner"].dropna().tolist() +
        matchups_df["team_b_owner"].dropna().tolist()
    ))

    col1, col2 = st.columns(2)
    with col1:
        selected_season = st.selectbox("Season", seasons, index=0, key="ps_season")
    with col2:
        selected_manager = st.selectbox("Manager", all_owners, key="ps_manager")

    has_idp = season_has_idp(roster_df, selected_season)
    exclude_def = bool(st.session_state.get("exclude_defensive", False)) and has_idp

    filtered_roster = filter_offensive_rosters(roster_df) if exclude_def else roster_df

    tab1, tab2, tab3 = st.tabs(["📋 Roster Stats", "⚔️ Matchup History", "🌟 Top Performers"])

    with tab1:
        _roster_tab(filtered_roster, selected_season, selected_manager)

    with tab2:
        _matchup_tab(matchups_df, selected_season, selected_manager)

    with tab3:
        _top_performers_tab(filtered_roster)


def _roster_tab(roster_df: pd.DataFrame, season: int, manager: str) -> None:
    df = roster_df[
        (roster_df["season"] == season) &
        (roster_df["owner_name"] == manager)
    ].copy()

    if df.empty:
        st.info("No roster data for this manager/season.")
        return

    show_all = st.checkbox("Show bench players too", key="ps_bench")
    if not show_all:
        df = df[df["starter"] == True]

    df = df.sort_values(["week", "points"], ascending=[True, False])

    starters_only = df[df["starter"] == True] if "starter" in df.columns else df
    if not starters_only.empty:
        weekly_totals = starters_only.groupby("week")["points"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Weekly Score", f"{weekly_totals.mean():.1f}")
        best_week_num = weekly_totals.idxmax()
        c2.metric("Best Week", f"Wk {int(best_week_num)} — {weekly_totals.max():.1f} pts")
        if not df["points"].isna().all():
            bp_idx = df["points"].idxmax()
            bp = df.loc[bp_idx]
            c3.metric("Best Single Game", f"{bp['player']} ({bp['points']:.1f})")

    display_cols = [c for c in ["week", "player", "position", "selected_position", "points", "projected", "starter"] if c in df.columns]
    rename = {
        "week": "Week", "player": "Player", "position": "Pos",
        "selected_position": "Slot", "points": "Pts", "projected": "Proj", "starter": "Starter",
    }
    out = df[display_cols].rename(columns=rename)
    if "Pts" in out.columns:
        out["Pts"] = pd.to_numeric(out["Pts"], errors="coerce").round(2)
    if "Proj" in out.columns:
        out["Proj"] = pd.to_numeric(out["Proj"], errors="coerce").round(2)
    styled = style_dataframe(out, higher_is_better=["Pts", "Proj"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _matchup_tab(matchups_df: pd.DataFrame, season: int, manager: str) -> None:
    df = matchups_df[matchups_df["season"] == season].copy()

    rows = []
    for _, row in df.iterrows():
        if row["team_a_owner"] == manager:
            my_pts = row["points_a"]
            opp_pts = row["points_b"]
            opponent = row["team_b_owner"]
            won = row["winner_team_id"] == row["team_a_id"]
        elif row["team_b_owner"] == manager:
            my_pts = row["points_b"]
            opp_pts = row["points_a"]
            opponent = row["team_a_owner"]
            won = row["winner_team_id"] == row["team_b_id"]
        else:
            continue

        if pd.isna(my_pts) or pd.isna(opp_pts):
            continue

        if row.get("is_championship"):
            game_type = "🏆 Championship"
        elif row.get("is_playoff"):
            game_type = "🎯 Playoff"
        elif row.get("is_consolation"):
            game_type = "🪦 Consolation"
        else:
            game_type = "Regular"

        rows.append({
            "Week": int(row["week"]) if pd.notna(row.get("week")) else "?",
            "Opponent": str(opponent),
            "My Score": round(float(my_pts), 2),
            "Opp Score": round(float(opp_pts), 2),
            "Margin": round(abs(float(my_pts) - float(opp_pts)), 2),
            "Result": "✅ W" if won else "❌ L",
            "Type": game_type,
        })

    if not rows:
        st.info("No matchups found for this manager/season.")
        return

    out = pd.DataFrame(rows).sort_values("Week")
    total_w = out["Result"].str.startswith("✅").sum()
    total_l = out["Result"].str.startswith("❌").sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Record", f"{total_w}-{total_l}")
    c2.metric("Avg Score", f"{out['My Score'].mean():.1f}")
    c3.metric("High Score", f"{out['My Score'].max():.2f}")

    styled = style_dataframe(out, higher_is_better=["My Score"], lower_is_better=["Opp Score"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _top_performers_tab(roster_df: pd.DataFrame) -> None:
    st.subheader("🌟 Top Single-Game Performances")

    if roster_df.empty:
        st.info("No roster data.")
        return

    starters = roster_df[roster_df["starter"] == True].copy() if "starter" in roster_df.columns else roster_df.copy()
    starters = starters.dropna(subset=["points"])
    starters = starters[starters["points"] > 0]

    if starters.empty:
        st.info("No starter data.")
        return

    top_cols = [c for c in ["player", "owner_name", "season", "week", "position", "points"] if c in starters.columns]
    top = starters.nlargest(25, "points")[top_cols].copy()
    top["points"] = top["points"].round(2)
    top.insert(0, "Rank", range(1, len(top) + 1))
    rename = {"player": "Player", "owner_name": "Owner", "season": "Season", "week": "Week", "position": "Pos", "points": "Pts"}
    top = top.rename(columns=rename)
    styled = style_dataframe(top, higher_is_better=["Pts"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.subheader("📊 Highest Scoring Weeks (Team Total)")
    group_cols = [c for c in ["season", "week", "owner_name"] if c in roster_df.columns]
    weekly_totals = (
        roster_df[roster_df["starter"] == True]
        .groupby(group_cols)["points"]
        .sum()
        .reset_index(name="total_pts")
        .dropna()
    )
    top_weeks = weekly_totals.nlargest(20, "total_pts").copy()
    top_weeks["total_pts"] = top_weeks["total_pts"].round(2)
    top_weeks.insert(0, "Rank", range(1, len(top_weeks) + 1))
    top_weeks = top_weeks.rename(columns={"season": "Season", "week": "Week", "owner_name": "Owner", "total_pts": "Total Pts"})
    styled2 = style_dataframe(top_weeks, higher_is_better=["Total Pts"])
    st.dataframe(styled2, use_container_width=True, hide_index=True)
