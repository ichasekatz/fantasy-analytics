"""Injury & bust impact: starters who significantly underperformed projections."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from utils import apply_league_filter

_BUST_THRESHOLD = 0.40   # actual / projected < 40% = "bust" event
_MIN_PROJECTED = 8.0     # ignore players projected under this (not expected to contribute)


def _bust_events(rosters_df: pd.DataFrame) -> pd.DataFrame:
    """Return starter rows where actual << projected (likely injured/inactive)."""
    df = rosters_df[
        rosters_df["starter"].fillna(False) &
        rosters_df["projected"].notna() &
        (rosters_df["projected"] >= _MIN_PROJECTED) &
        rosters_df["points"].notna()
    ].copy()
    df["pct_of_proj"] = df["points"] / df["projected"].replace(0, float("nan"))
    return df[df["pct_of_proj"] < _BUST_THRESHOLD].copy()


def render(conn) -> None:
    st.title("🩺 Injury Impact")
    st.caption(
        "Starters projected ≥ 8 pts who scored < 40% of projection — "
        "likely injured, inactive, or benched by coaching. Based on Sleeper projections."
    )

    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    if rosters_df.empty or "projected" not in rosters_df.columns:
        st.info("No roster projection data available.")
        return

    busts = _bust_events(rosters_df)

    if busts.empty:
        st.info("No bust events found with current thresholds.")
        return

    seasons = sorted(rosters_df["season"].dropna().unique(), reverse=True)
    owners = sorted(rosters_df["owner_name"].dropna().unique())

    tab_overview, tab_manager, tab_player, tab_timing = st.tabs([
        "League Overview", "By Manager", "By Player", "Injury Timing",
    ])

    # ── Overview ────────────────────────────────────────────────────────────
    with tab_overview:
        sel_season = st.selectbox("Season", seasons, key="inj_ov_season")
        s_busts = busts[busts["season"] == sel_season]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bust events", len(s_busts))
        c2.metric("Managers affected", s_busts["owner_name"].nunique())
        c3.metric("Unique players", s_busts["player"].nunique())
        pts_lost = (s_busts["projected"] - s_busts["points"]).sum()
        c4.metric("Pts lost vs proj", f"{pts_lost:.1f}")

        st.divider()

        if not s_busts.empty:
            burden = (
                s_busts.groupby("owner_name")
                .apply(lambda x: (x["projected"] - x["points"]).sum(), include_groups=False)
                .reset_index(name="pts_lost")
                .sort_values("pts_lost", ascending=False)
                .rename(columns={"owner_name": "Manager"})
            )
            fig = px.bar(
                burden, x="Manager", y="pts_lost",
                labels={"pts_lost": "Pts Lost vs Projection"},
                color="pts_lost",
                color_continuous_scale="Reds",
                title=f"{sel_season} — Projected pts lost to busts/injuries by manager",
            )
            fig.update_coloraxes(showscale=False)
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("All bust events this season"):
                display = s_busts[["week", "owner_name", "player", "position",
                                    "projected", "points", "pct_of_proj"]].rename(columns={
                    "owner_name": "Manager", "player": "Player", "position": "Pos",
                    "projected": "Proj", "points": "Actual", "pct_of_proj": "% of Proj",
                }).copy()
                display["% of Proj"] = (display["% of Proj"] * 100).round(1).astype(str) + "%"
                display["Proj"] = display["Proj"].round(1)
                display["Actual"] = display["Actual"].round(1)
                st.dataframe(display.sort_values(["week", "Manager"]),
                             use_container_width=True, hide_index=True)

    # ── By Manager ──────────────────────────────────────────────────────────
    with tab_manager:
        sel_mgr = st.selectbox("Manager", owners, key="inj_mgr")
        mgr_busts = busts[busts["owner_name"] == sel_mgr]

        if mgr_busts.empty:
            st.info("No bust events for this manager.")
        else:
            c1, c2, c3 = st.columns(3)
            total_lost = (mgr_busts["projected"] - mgr_busts["points"]).sum()
            c1.metric("Bust events", len(mgr_busts))
            c2.metric("Total pts lost", f"{total_lost:.1f}")
            c3.metric("Seasons affected", mgr_busts["season"].nunique())

            by_season = (
                mgr_busts.groupby("season")
                .apply(lambda x: (x["projected"] - x["points"]).sum(), include_groups=False)
                .reset_index(name="pts_lost")
            )
            fig = px.bar(by_season, x="season", y="pts_lost",
                         labels={"season": "Season", "pts_lost": "Pts Lost vs Proj"},
                         title=f"{sel_mgr} — Pts lost to busts by season",
                         color_discrete_sequence=["#ef4444"])
            st.plotly_chart(fig, use_container_width=True)

            detail = mgr_busts[["season", "week", "player", "position",
                                  "projected", "points", "pct_of_proj"]].rename(columns={
                "player": "Player", "position": "Pos",
                "projected": "Proj", "points": "Actual", "pct_of_proj": "% of Proj",
            }).copy()
            detail["% of Proj"] = (detail["% of Proj"] * 100).round(1).astype(str) + "%"
            detail["Proj"] = detail["Proj"].round(1)
            detail["Actual"] = detail["Actual"].round(1)
            st.dataframe(detail.sort_values(["season", "week"]),
                         use_container_width=True, hide_index=True)

    # ── By Player ───────────────────────────────────────────────────────────
    with tab_player:
        search = st.text_input("Search player", placeholder="e.g. Davante Adams")
        df = busts.copy()
        if search:
            df = df[df["player"].str.contains(search, case=False, na=False)]

        if df.empty:
            st.info("No bust records found." if search else "Enter a player name to search.")
        else:
            summary = (
                df.groupby("player")
                .agg(
                    bust_weeks=("week", "count"),
                    seasons=("season", "nunique"),
                    pts_lost=("points", lambda x: (df.loc[x.index, "projected"] - x).sum()),
                    managers=("owner_name", lambda x: ", ".join(sorted(x.unique()))),
                )
                .reset_index()
                .rename(columns={
                    "player": "Player", "bust_weeks": "Bust Weeks",
                    "seasons": "Seasons", "pts_lost": "Total Pts Lost", "managers": "Owned By",
                })
                .sort_values("Bust Weeks", ascending=False)
            )
            summary["Total Pts Lost"] = summary["Total Pts Lost"].round(1)
            st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── Injury Timing ───────────────────────────────────────────────────────
    with tab_timing:
        st.subheader("Did bust events cost wins?")
        st.caption("Weeks with a bust starter — did the manager win or lose?")

        team_a = matchups_df[["season", "week", "team_a_owner", "winner_team_id", "team_a_id"]].rename(
            columns={"team_a_owner": "owner", "team_a_id": "my_id"}
        )
        team_b = matchups_df[["season", "week", "team_b_owner", "winner_team_id", "team_b_id"]].rename(
            columns={"team_b_owner": "owner", "team_b_id": "my_id"}
        )
        all_games = pd.concat([team_a, team_b], ignore_index=True)
        all_games["won"] = all_games["winner_team_id"] == all_games["my_id"]

        bust_weeks = (
            busts[["season", "week", "owner_name", "player", "projected", "points"]]
            .merge(all_games[["season", "week", "owner", "won"]],
                   left_on=["season", "week", "owner_name"],
                   right_on=["season", "week", "owner"], how="left")
            .dropna(subset=["won"])
        )

        if bust_weeks.empty:
            st.info("Could not match bust weeks to matchup results.")
        else:
            unique_weeks = bust_weeks[["season", "week", "owner_name", "won"]].drop_duplicates()
            total = len(unique_weeks)
            lost = int((unique_weeks["won"] == False).sum())
            won = total - lost

            c1, c2, c3 = st.columns(3)
            c1.metric("Weeks with bust starter", total)
            c2.metric("Won despite bust", won)
            c3.metric("Lost with bust starter", lost)

            st.divider()
            loss_rows = unique_weeks[unique_weeks["won"] == False].merge(
                bust_weeks[["season", "week", "owner_name", "player", "projected", "points"]],
                on=["season", "week", "owner_name"],
            ).rename(columns={
                "owner_name": "Manager", "player": "Bust Player",
                "projected": "Proj", "points": "Actual",
            })
            loss_rows["Proj"] = loss_rows["Proj"].round(1)
            loss_rows["Actual"] = loss_rows["Actual"].round(1)
            if not loss_rows.empty:
                st.subheader("Loss weeks with bust starters")
                st.dataframe(loss_rows.drop(columns=["won"]).sort_values(["season", "week"]),
                             use_container_width=True, hide_index=True)
