"""Injury impact analysis: NFL injury report data crossed with fantasy rosters."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from utils import apply_league_filter

_injuries_path = Path(__file__).parents[2] / "data" / "external" / "nfl_injuries.parquet"

_status_order = {"Out": 0, "Doubtful": 1, "Questionable": 2, "Note": 3}
_status_color = {"Out": "#ef4444", "Doubtful": "#f97316", "Questionable": "#eab308", "Note": "#64748b"}


@st.cache_data
def _load_injuries() -> pd.DataFrame:
    if not _injuries_path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(_injuries_path)
    df["season"] = df["season"].astype(int)
    df["week"] = df["week"].astype(int)
    return df[df["game_type"] == "REG"].copy()


def render(conn) -> None:
    """Render the Injury Impact page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🩺 Injury Impact")

    inj_df = _load_injuries()
    if inj_df.empty:
        st.error("Injury data not found. Run the data refresh to fetch it.")
        return

    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    if rosters_df.empty:
        st.info("No roster data available for the selected league.")
        return

    # Merge injury report onto rosters by player name + season + week
    # Use full_name from injury data; player from rosters
    merged = rosters_df.merge(
        inj_df[["season", "week", "full_name", "position", "report_status",
                "report_primary_injury", "practice_status"]],
        left_on=["season", "week", "player"],
        right_on=["season", "week", "full_name"],
        how="inner",
    )
    merged = merged[merged["report_status"].notna()]

    seasons = sorted(rosters_df["season"].unique(), reverse=True)
    owners = sorted(rosters_df["owner_name"].dropna().unique())

    tab_overview, tab_manager, tab_player, tab_timing = st.tabs([
        "League Overview", "By Manager", "By Player", "Injury Timing",
    ])

    with tab_overview:
        _render_overview(merged, inj_df, seasons)

    with tab_manager:
        _render_by_manager(merged, matchups_df, owners, seasons)

    with tab_player:
        _render_by_player(merged, seasons)

    with tab_timing:
        _render_timing(merged, matchups_df)


def _render_overview(merged: pd.DataFrame, inj_df: pd.DataFrame, seasons: list) -> None:
    selected_season = st.selectbox("Season", seasons, key="inj_overview_season")
    season_inj = merged[merged["season"] == selected_season]

    col1, col2, col3, col4 = st.columns(4)
    out_count = len(season_inj[season_inj["report_status"] == "Out"])
    q_count = len(season_inj[season_inj["report_status"] == "Questionable"])
    d_count = len(season_inj[season_inj["report_status"] == "Doubtful"])
    starters_hurt = len(season_inj[season_inj["starter"] == True])
    col1.metric("Out designations", out_count)
    col2.metric("Doubtful", d_count)
    col3.metric("Questionable", q_count)
    col4.metric("Starter injuries", starters_hurt)

    st.divider()

    # Injury burden by team (points lost from injured starters)
    st.subheader("Injury Burden by Manager (starter pts lost to injury)")
    starter_out = season_inj[(season_inj["starter"] == True) & (season_inj["report_status"].isin(["Out", "Doubtful"]))]
    if not starter_out.empty:
        burden = (
            starter_out.groupby("owner_name")["points"]
            .agg(games="count", pts_lost="sum")
            .reset_index()
            .rename(columns={"owner_name": "Manager", "games": "Games w/ Injured Starter", "pts_lost": "Total Pts Lost"})
            .sort_values("Total Pts Lost")
        )
        fig = px.bar(
            burden, x="Total Pts Lost", y="Manager", orientation="h",
            color_discrete_sequence=["#ef4444"],
            labels={"Total Pts Lost": "Points from injured starters (Out/Doubtful)"},
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Points scored by starters designated Out or Doubtful that week.")
    else:
        st.info("No Out/Doubtful starter data for this season.")

    # Raw table
    with st.expander("All injury events this season"):
        display = season_inj[["week", "owner_name", "player", "position_x", "report_status", "report_primary_injury", "starter", "points"]].rename(columns={
            "owner_name": "Manager", "player": "Player", "position_x": "Pos",
            "report_status": "Status", "report_primary_injury": "Injury",
            "starter": "Starter", "points": "Pts Scored",
        })
        display = display.sort_values(["week", "Status"])
        st.dataframe(display, use_container_width=True, hide_index=True)


def _render_by_manager(merged: pd.DataFrame, matchups_df: pd.DataFrame,
                       owners: list, seasons: list) -> None:
    selected = st.selectbox("Manager", owners, key="inj_manager")
    mgr_inj = merged[merged["owner_name"] == selected]

    if mgr_inj.empty:
        st.info("No injury events found for this manager.")
        return

    col1, col2 = st.columns(2)
    with col1:
        total = len(mgr_inj)
        out = len(mgr_inj[mgr_inj["report_status"] == "Out"])
        starter_out = len(mgr_inj[(mgr_inj["starter"] == True) & (mgr_inj["report_status"] == "Out")])
        st.metric("Total injury-week events", total)
        st.metric("'Out' designations", out)
        st.metric("Injured starters (Out)", starter_out)

    with col2:
        pts_lost = mgr_inj[(mgr_inj["starter"] == True) & (mgr_inj["report_status"].isin(["Out","Doubtful"]))]["points"].sum()
        seasons_played = mgr_inj["season"].nunique()
        st.metric("Starter pts lost (Out/Doubtful)", f"{pts_lost:.1f}")
        st.metric("Seasons affected", seasons_played)

    st.divider()
    st.subheader("Injury events by season")
    by_season = mgr_inj.groupby(["season", "report_status"]).size().reset_index(name="count")
    fig = px.bar(by_season, x="season", y="count", color="report_status",
                 color_discrete_map=_status_color,
                 labels={"season": "Season", "count": "Injury Events", "report_status": "Status"})
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("All injury events")
    display = mgr_inj[["season", "week", "player", "position_x", "report_status",
                        "report_primary_injury", "starter", "points"]].rename(columns={
        "player": "Player", "position_x": "Pos", "report_status": "Status",
        "report_primary_injury": "Injury", "starter": "Starter", "points": "Pts",
    }).sort_values(["season", "week"])
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_by_player(merged: pd.DataFrame, seasons: list) -> None:
    search = st.text_input("Search player", placeholder="e.g. Davante Adams")
    df = merged.copy()
    if search:
        df = df[df["player"].str.contains(search, case=False, na=False)]

    if df.empty:
        st.info("No injury records found." if search else "Enter a player name to search.")
        return

    # Group by player
    summary = df.groupby("player").agg(
        seasons=("season", "nunique"),
        injury_weeks=("week", "count"),
        out_weeks=("report_status", lambda x: (x == "Out").sum()),
        pts_while_hurt=("points", "sum"),
        managers=("owner_name", lambda x: ", ".join(sorted(x.unique()))),
    ).reset_index().rename(columns={
        "player": "Player", "seasons": "Seasons",
        "injury_weeks": "Injury Weeks", "out_weeks": "Out Weeks",
        "pts_while_hurt": "Pts Scored While Hurt", "managers": "Owned By",
    }).sort_values("Out Weeks", ascending=False)

    st.dataframe(summary, use_container_width=True, hide_index=True)

    if search and not df.empty:
        st.divider()
        st.subheader(f"All events — {df['player'].iloc[0]}")
        detail = df[["season", "week", "owner_name", "report_status", "report_primary_injury", "starter", "points"]].rename(columns={
            "owner_name": "Manager", "report_status": "Status",
            "report_primary_injury": "Injury", "starter": "Starter", "points": "Pts",
        }).sort_values(["season", "week"])
        st.dataframe(detail, use_container_width=True, hide_index=True)


def _render_timing(merged: pd.DataFrame, matchups_df: pd.DataFrame) -> None:
    st.subheader("Injury timing: did injuries cost wins?")
    st.caption("Weeks where a manager had an Out/Doubtful starter and lost that week's matchup.")

    out_starters = merged[
        (merged["starter"] == True) &
        (merged["report_status"].isin(["Out", "Doubtful"]))
    ][["season", "week", "owner_name", "player", "points"]].copy()

    if out_starters.empty:
        st.info("No Out/Doubtful starter data available.")
        return

    # Join to matchup results
    team_a = matchups_df[["season", "week", "team_a_owner", "points_a", "winner_team_id", "team_a_id"]].rename(
        columns={"team_a_owner": "owner", "points_a": "team_pts", "team_a_id": "my_team_id"}
    )
    team_b = matchups_df[["season", "week", "team_b_owner", "points_b", "winner_team_id", "team_b_id"]].rename(
        columns={"team_b_owner": "owner", "points_b": "team_pts", "team_b_id": "my_team_id"}
    )
    all_games = pd.concat([team_a, team_b], ignore_index=True)
    all_games["won"] = all_games["winner_team_id"] == all_games["my_team_id"]

    hurt_weeks = out_starters.merge(
        all_games[["season", "week", "owner", "team_pts", "won"]],
        left_on=["season", "week", "owner_name"],
        right_on=["season", "week", "owner"],
        how="left",
    ).dropna(subset=["won"])

    if hurt_weeks.empty:
        st.info("Could not match injury weeks to matchup results.")
        return

    total = len(hurt_weeks[["season", "week", "owner_name"]].drop_duplicates())
    losses = hurt_weeks[hurt_weeks["won"] == False][["season", "week", "owner_name"]].drop_duplicates()
    wins = total - len(losses)

    col1, col2, col3 = st.columns(3)
    col1.metric("Weeks with Out/Doubtful starter", total)
    col2.metric("Won despite injury", wins)
    col3.metric("Lost with injured starter", len(losses))

    st.divider()
    if not losses.empty:
        st.subheader("Painful losses — Out/Doubtful starter on loss week")
        loss_detail = losses.merge(
            hurt_weeks[["season", "week", "owner_name", "player", "points", "team_pts"]],
            on=["season", "week", "owner_name"],
        ).rename(columns={
            "owner_name": "Manager", "player": "Injured Player",
            "points": "Injured Pts", "team_pts": "Team Score",
        })
        st.dataframe(loss_detail, use_container_width=True, hide_index=True)
