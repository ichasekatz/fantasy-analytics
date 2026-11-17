"""Player Hall of Fame: greatest NFL players in league fantasy history."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.player_ownership import player_career_stats, player_ownership_history
from style import inject_css
from utils import apply_league_filter, is_non_skill_position, style_dataframe

_POS_COLORS = {"QB": "#E53E3E", "RB": "#38A169", "WR": "#3182CE", "TE": "#D69E2E", "K": "#718096", "DST": "#805AD5"}


def render(conn) -> None:
    st.title("🌟 Player Hall of Fame")
    st.caption("Greatest NFL players in Bigwell's Leaguern fantasy history")
    inject_css()

    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks").df())

    if rosters_df.empty:
        st.info("No roster data available.")
        return

    career = player_career_stats(rosters_df, draft_df)
    if career.empty:
        st.info("No player data.")
        return

    tab1, tab2, tab3 = st.tabs(["All-Time Greats", "By Season", "Categories"])

    with tab1:
        _render_all_time(career)

    with tab2:
        _render_by_season(rosters_df, draft_df)

    with tab3:
        _render_categories(career, rosters_df, draft_df)


def _render_all_time(career) -> None:
    total_players = len(career)
    total_pts = career["total_started_points"].sum()
    c1, c2 = st.columns(2)
    c1.metric("Unique Players Ever Rostered", f"{total_players:,}")
    c2.metric("Total Started Points Recorded", f"{total_pts:,.1f}")

    top25 = career.head(25).copy()
    top25.insert(0, "Rank", range(1, len(top25) + 1))
    display = top25[["Rank", "player", "position", "total_started_points", "total_managers", "total_seasons", "best_owner"]].rename(columns={
        "player": "Player", "position": "Pos", "total_started_points": "Started Pts",
        "total_managers": "Managers", "total_seasons": "Seasons", "best_owner": "Best Owner",
    })
    styled_hof = style_dataframe(display, higher_is_better=["Started Pts", "Managers", "Seasons"], lower_is_better=["Rank"])
    st.dataframe(styled_hof, use_container_width=True, hide_index=True)

    top15 = career.head(15).copy()
    top15["color"] = top15["position"].map(_POS_COLORS).fillna("#718096")
    fig = px.bar(
        top15, x="player", y="total_started_points",
        color="position",
        color_discrete_map=_POS_COLORS,
        labels={"player": "Player", "total_started_points": "Total Started Pts", "position": "Position"},
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)


def _render_by_season(rosters_df, draft_df) -> None:
    seasons = sorted(rosters_df["season"].unique(), reverse=True)
    if not seasons:
        st.info("No seasons.")
        return

    sel_season = st.selectbox("Season", seasons, key="phof_season")
    pos_filter = st.multiselect("Position", ["QB", "RB", "WR", "TE", "K", "DST"], default=[], key="phof_pos")

    season_rosters = rosters_df[rosters_df["season"] == sel_season]
    season_draft = draft_df[draft_df["season"] == sel_season] if not draft_df.empty else draft_df
    season_career = player_career_stats(season_rosters, season_draft)

    if pos_filter:
        season_career = season_career[season_career["position"].isin(pos_filter)]

    if season_career.empty:
        st.info("No data for this selection.")
        return

    top20 = season_career.head(20).copy()
    top20.insert(0, "Rank", range(1, len(top20) + 1))
    display = top20[["Rank", "player", "position", "total_started_points", "total_roster_points", "best_owner"]].rename(columns={
        "player": "Player", "position": "Pos", "total_started_points": "Started Pts",
        "total_roster_points": "Roster Pts", "best_owner": "Owner",
    })
    styled_season = style_dataframe(display, higher_is_better=["Started Pts", "Roster Pts"], lower_is_better=["Rank"])
    st.dataframe(styled_season, use_container_width=True, hide_index=True)


def _render_categories(career, rosters_df, draft_df) -> None:
    if st.checkbox("Exclude defensive players (IDP)", value=True, key="phof_cat_excl_def"):
        career = career[~career["position"].apply(
            lambda p: is_non_skill_position(str(p)) if p and str(p) != "nan" else False
        )]

    st.subheader("Most Consistently Drafted")
    most_drafted = career[career["times_drafted"] > 0].sort_values("times_drafted", ascending=False).head(20)
    _show_category(most_drafted, ["player", "position", "times_drafted", "total_seasons", "total_started_points"],
                   {"player": "Player", "position": "Pos", "times_drafted": "Times Drafted", "total_seasons": "Seasons", "total_started_points": "Started Pts"},
                   higher_is_better=["Times Drafted", "Seasons", "Started Pts"])

    st.divider()
    st.subheader("One-Season Wonders")
    wonders = career[(career["total_seasons"] == 1) & (career["total_started_points"] > 40)].sort_values("total_started_points", ascending=False).head(20)
    _show_category(wonders, ["player", "position", "total_started_points", "best_owner"],
                   {"player": "Player", "position": "Pos", "total_started_points": "Started Pts", "best_owner": "Owner"},
                   higher_is_better=["Started Pts"])

    st.divider()
    st.subheader("Most Managers — Passed Around the Most")
    most_owners = career.sort_values("total_managers", ascending=False).head(20)
    _show_category(most_owners, ["player", "position", "total_managers", "total_seasons", "total_started_points"],
                   {"player": "Player", "position": "Pos", "total_managers": "Managers", "total_seasons": "Seasons", "total_started_points": "Started Pts"},
                   higher_is_better=["Managers", "Seasons", "Started Pts"])

    st.divider()
    st.subheader("Franchise Cornerstones")
    st.caption(
        "Players whose best owner scored ≥ 55% of their fantasy points **within a single league** "
        "and appeared in ≥ 3 seasons — truly built around one manager."
    )
    # Compute cornerstones per-league so cross-league ownership doesn't dilute loyalty %
    _cs_rows = []
    for _lid, _ldf in rosters_df.groupby("league_id") if "league_id" in rosters_df.columns else [(None, rosters_df)]:
        _dddf = draft_df[draft_df["league_id"] == _lid] if (_lid and "league_id" in draft_df.columns) else draft_df
        _lc = player_career_stats(_ldf, _dddf)
        if _lc.empty:
            continue
        if st.session_state.get("phof_cat_excl_def"):
            _lc = _lc[~_lc["position"].apply(lambda p: is_non_skill_position(str(p)) if p and str(p) != "nan" else False)]
        if "best_owner_points" in _lc.columns:
            _lc = _lc[_lc["total_started_points"] > 0].copy()
            _lc["loyalty_pct"] = _lc["best_owner_points"] / _lc["total_started_points"]
            _lc = _lc[(_lc["loyalty_pct"] >= 0.55) & (_lc["total_seasons"] >= 3)]
            _lc["league_id_col"] = _lid
            _cs_rows.append(_lc)
    if _cs_rows:
        import pandas as pd
        _cs_all = pd.concat(_cs_rows, ignore_index=True)
        # Keep best (highest started pts) entry per player
        _cs_all = _cs_all.sort_values("total_started_points", ascending=False).drop_duplicates(subset=["player"]).head(20)
        _cs_all["Loyalty %"] = (_cs_all["loyalty_pct"] * 100).round(1)
        _show_category(_cs_all, ["player", "position", "total_seasons", "total_started_points", "best_owner", "Loyalty %"],
                       {"player": "Player", "position": "Pos", "total_seasons": "Seasons", "total_started_points": "Started Pts", "best_owner": "Owner"},
                       higher_is_better=["Seasons", "Started Pts", "Loyalty %"])
    else:
        st.info("No franchise cornerstones found.")


def _show_category(df, cols, rename, higher_is_better=None, lower_is_better=None) -> None:
    if df.empty:
        st.info("None found.")
        return
    available = [c for c in cols if c in df.columns]
    display = df[available].rename(columns=rename)
    st.dataframe(
        style_dataframe(display, higher_is_better=higher_is_better or [], lower_is_better=lower_is_better or []),
        use_container_width=True, hide_index=True,
    )
