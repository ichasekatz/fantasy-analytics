"""Player Ownership History: who owned each player, repeat owners, and ownership network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.player_ownership import player_career_stats, player_ownership_history
from style import inject_css
from utils import apply_league_filter, style_dataframe


def render(conn) -> None:
    st.title("👑 Player Ownership")
    inject_css()

    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks").df())
    transactions_df = conn.execute("SELECT * FROM transactions WHERE type = 'trade'").df()

    if rosters_df.empty:
        st.info("No roster data available.")
        return

    tab1, tab2, tab3 = st.tabs(["Player History", "Repeat Owners", "Ownership Network"])

    with tab1:
        _render_player_history(rosters_df, draft_df)

    with tab2:
        _render_repeat_owners(draft_df)

    with tab3:
        _render_ownership_network(rosters_df, transactions_df)


def _render_player_history(rosters_df: pd.DataFrame, draft_df: pd.DataFrame) -> None:
    career = player_career_stats(rosters_df, draft_df)
    if career.empty:
        st.info("No player data.")
        return

    search = st.text_input("Search player", placeholder="e.g. Josh Allen, CMC…", key="po_search")

    if search:
        matches = career[career["player"].str.contains(search, case=False, na=False)]
    else:
        matches = pd.DataFrame()

    if search and len(matches) == 1:
        p = matches.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Managers", int(p["total_managers"]))
        c2.metric("Seasons", int(p["total_seasons"]))
        c3.metric("Started Pts", f"{p['total_started_points']:.1f}")
        c4.metric("Best Owner", p["best_owner"] or "—")

        history = player_ownership_history(rosters_df, draft_df)
        player_hist = history[history["player"] == p["player"]].sort_values(["season", "owner_name"])
        if not player_hist.empty:
            display = player_hist[["season", "owner_name", "was_drafted", "weeks_owned", "weeks_started", "started_points", "total_points"]].rename(columns={
                "season": "Season", "owner_name": "Owner", "was_drafted": "Drafted",
                "weeks_owned": "Wks Owned", "weeks_started": "Wks Started",
                "started_points": "Started Pts", "total_points": "Total Pts",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)

            if len(player_hist) > 1:
                fig = px.bar(
                    player_hist, x="season", y="started_points", color="owner_name",
                    labels={"season": "Season", "started_points": "Started Points", "owner_name": "Owner"},
                    barmode="group",
                )
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

    elif search and len(matches) > 1:
        st.caption(f"{len(matches)} players found — showing all")
        _show_career_table(matches.head(50))
    else:
        st.caption("Top 50 players by started points")
        _show_career_table(career.head(50))


def _show_career_table(df: pd.DataFrame) -> None:
    df = df.copy()
    df.insert(0, "Rank", range(1, len(df) + 1))
    display = df[["Rank", "player", "position", "total_started_points", "total_managers", "total_seasons", "best_owner"]].rename(columns={
        "player": "Player", "position": "Pos", "total_started_points": "Started Pts",
        "total_managers": "Managers", "total_seasons": "Seasons", "best_owner": "Best Owner",
    })
    styled = style_dataframe(display, higher_is_better=["Started Pts", "Managers", "Seasons"], lower_is_better=["Rank"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_repeat_owners(draft_df: pd.DataFrame) -> None:
    st.subheader("Managers Who Keep Drafting the Same Player")
    if draft_df.empty:
        st.info("No draft data.")
        return

    repeat = (
        draft_df.groupby(["owner_name", "player"])
        .agg(times_drafted=("season", "count"), seasons=("season", lambda x: sorted(x.tolist())))
        .reset_index()
    )
    repeat = repeat[repeat["times_drafted"] > 1].sort_values("times_drafted", ascending=False)

    if repeat.empty:
        st.info("No player was drafted by the same manager more than once.")
        return

    repeat["seasons"] = repeat["seasons"].apply(lambda s: ", ".join(str(x) for x in s))
    repeat_display = repeat.rename(columns={"owner_name": "Manager", "player": "Player", "times_drafted": "Times Drafted", "seasons": "Seasons"})
    st.dataframe(
        style_dataframe(repeat_display, higher_is_better=["Times Drafted"]),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Most Repeat Picks by Manager")
    mgr_repeat = repeat.groupby("owner_name")["times_drafted"].sum().reset_index().sort_values("times_drafted", ascending=False)
    mgr_repeat.columns = ["Manager", "Total Repeat Draft Picks"]
    st.dataframe(
        style_dataframe(mgr_repeat, higher_is_better=["Total Repeat Draft Picks"]),
        use_container_width=True, hide_index=True,
    )


def _render_ownership_network(rosters_df: pd.DataFrame, transactions_df: pd.DataFrame) -> None:
    st.subheader("Shared Ownership — Managers Who Owned the Same Players")

    history = player_ownership_history(rosters_df, pd.DataFrame())
    if history.empty:
        st.info("No data.")
        return

    player_owners = history.groupby("player")["owner_name"].apply(set).reset_index()
    player_owners = player_owners[player_owners["owner_name"].apply(len) > 1]

    pairs: dict[tuple[str, str], int] = {}
    for _, row in player_owners.iterrows():
        owners = sorted(row["owner_name"])
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                key = (owners[i], owners[j])
                pairs[key] = pairs.get(key, 0) + 1

    if not pairs:
        st.info("No shared ownership found.")
    else:
        pair_df = pd.DataFrame(
            [{"Manager A": a, "Manager B": b, "Shared Players": n} for (a, b), n in pairs.items()]
        ).sort_values("Shared Players", ascending=False).head(30)
        st.dataframe(style_dataframe(pair_df, higher_is_better=["Shared Players"]), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Most Frequently Traded Players")
    if transactions_df.empty:
        st.info("No trade data.")
        return

    player_counts: dict[str, int] = {}
    for _, row in transactions_df.iterrows():
        try:
            players = json.loads(row["players"]) if isinstance(row["players"], str) else (row["players"] or [])
            for p in players:
                if isinstance(p, dict):
                    name = p.get("player") or p.get("name") or ""
                    if name:
                        player_counts[name] = player_counts.get(name, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    if player_counts:
        trade_df = pd.DataFrame(list(player_counts.items()), columns=["Player", "Times Traded"]).sort_values("Times Traded", ascending=False).head(25)
        st.dataframe(style_dataframe(trade_df, higher_is_better=["Times Traded"]), use_container_width=True, hide_index=True)
