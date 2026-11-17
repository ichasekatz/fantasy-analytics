"""Injury analysis page: proxy injury detection from scoring patterns."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

_ext_weekly = Path(__file__).parents[2] / "data" / "external" / "nfl_weekly_stats.parquet"

# Points threshold below which a started player is treated as "likely unavailable"
_zero_game_threshold = 3.0
# Fraction of positional average below which a drafted player is "likely impacted"
_impact_threshold = 0.5


@st.cache_data
def _rosters(_conn) -> pd.DataFrame:
    """Load all roster data.

    Args:
        _conn: DuckDB connection.

    Returns:
        Rosters DataFrame.
    """
    return _conn.execute("SELECT * FROM rosters").df()


@st.cache_data
def _draft_picks(_conn) -> pd.DataFrame:
    """Load draft picks.

    Args:
        _conn: DuckDB connection.

    Returns:
        Draft picks DataFrame.
    """
    return _conn.execute("SELECT season, overall, round, owner_name, player, position FROM draft_picks").df()


def render(conn) -> None:
    """Render the Injury Analysis page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("💊 Injury Analysis")
    st.warning(
        "⚠️ Injury data is approximated from scoring patterns. "
        "A player scoring below threshold is flagged as 'likely impacted' — "
        "this may include healthy players who had a bad game. "
        "For verified injury history, external sources are needed."
    )

    rosters_df = _rosters(conn)
    draft_df = _draft_picks(conn)
    league_id: str | None = st.session_state.get("selected_league_id")
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()

    seasons = sorted(rosters_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_opts = ["All Seasons"] + [f"{s} ({provider_map.get(s,'?')})" for s in seasons]
    season_label = st.selectbox("Season", season_opts, index=len(season_opts) - 1)
    selected_season: int | None = None if season_label == "All Seasons" else seasons[season_opts.index(season_label) - 1]

    if league_id and "league_id" in rosters_df.columns:
        rosters_df = rosters_df[rosters_df["league_id"] == league_id].copy()
    if selected_season is not None:
        rosters_df = rosters_df[rosters_df["season"] == selected_season].copy()
        draft_df = draft_df[draft_df["season"] == selected_season].copy()

    if rosters_df.empty:
        st.info("No roster data for this selection.")
        return

    tab1, tab2 = st.tabs(["Drafted Player Impact", "Manager Injury Burden"])

    with tab1:
        st.subheader("Low-Production Drafted Players")
        st.caption(
            f"Drafted players who scored < {int(_impact_threshold * 100)}% of their "
            "positional average are flagged as 'Likely Impacted'."
        )

        # Compute positional averages per season from roster starters
        starters = rosters_df[rosters_df["starter"] == True].copy()
        pos_avg = starters.groupby(["season", "position"])["points"].mean().reset_index()
        pos_avg.columns = ["season", "position", "pos_avg"]

        # Aggregate drafted player performance
        player_perf = rosters_df.groupby(["season", "player", "position"])["points"].sum().reset_index()
        player_perf.columns = ["season", "player", "position", "total_points"]

        # Join draft info
        picks_perf = draft_df.merge(player_perf, on=["season", "player", "position"], how="left")
        picks_perf = picks_perf.merge(pos_avg, on=["season", "position"], how="left")
        picks_perf = picks_perf.dropna(subset=["pos_avg"])

        # Normalize to 17-game equivalent
        week_counts = rosters_df.groupby("season")["week"].nunique().reset_index()
        week_counts.columns = ["season", "num_weeks"]
        picks_perf = picks_perf.merge(week_counts, on="season", how="left")
        picks_perf["expected_full_season"] = picks_perf["pos_avg"] * picks_perf["num_weeks"].fillna(13)
        picks_perf["pct_of_avg"] = (picks_perf["total_points"] / picks_perf["expected_full_season"].replace(0, pd.NA)).round(3)
        picks_perf["flag"] = picks_perf["pct_of_avg"].apply(
            lambda x: "⚠️ Likely Impacted" if pd.notna(x) and x < _impact_threshold else "✅ Normal"
        )

        impacted = picks_perf[picks_perf["pct_of_avg"] < _impact_threshold].copy()
        if impacted.empty:
            st.info("No significantly impacted drafted players found.")
        else:
            impacted["total_points"] = impacted["total_points"].fillna(0).round(2)
            impacted["expected_full_season"] = impacted["expected_full_season"].round(2)
            impacted["pct_of_avg"] = (impacted["pct_of_avg"] * 100).round(1)
            display = impacted[[
                "season", "owner_name", "player", "position", "round",
                "total_points", "expected_full_season", "pct_of_avg", "flag",
            ]].rename(columns={
                "season": "Season", "owner_name": "Owner", "player": "Player",
                "position": "Pos", "round": "Rd",
                "total_points": "Actual Pts", "expected_full_season": "Expected Pts",
                "pct_of_avg": "% of Avg", "flag": "Status",
            }).sort_values(["Season", "% of Avg"])
            st.dataframe(display, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Manager Injury Burden")
        st.caption(
            f"Impacted starter-weeks = weeks where a started player scored < {_zero_game_threshold} points "
            "(proxy for missing/injured). Higher = more injury-related suffering."
        )

        # Starter weeks with near-zero scores
        starters_all = rosters_df[rosters_df["starter"] == True].copy()
        starters_all["impacted"] = starters_all["points"] < _zero_game_threshold
        burden = starters_all.groupby(["season", "owner_name"]).agg(
            impacted_starter_weeks=("impacted", "sum"),
            total_starter_weeks=("impacted", "count"),
        ).reset_index()
        burden["impact_rate"] = (burden["impacted_starter_weeks"] / burden["total_starter_weeks"].replace(0, pd.NA) * 100).round(1)
        burden = burden.sort_values("impacted_starter_weeks", ascending=False)

        display2 = burden.rename(columns={
            "season": "Season", "owner_name": "Manager",
            "impacted_starter_weeks": "Impacted Starter-Wks",
            "total_starter_weeks": "Total Starter-Wks",
            "impact_rate": "Impact Rate (%)",
        })
        st.dataframe(display2, use_container_width=True, hide_index=True)

        # External data: zero-point weeks per player
        search_player = st.text_input("Check a specific player's weekly scores (requires external data)")
        if _ext_weekly.exists() and search_player:
            try:
                nfl_w = pd.read_parquet(_ext_weekly)
                player_weeks = nfl_w[nfl_w["player_name"].str.contains(search_player, case=False, na=False)]
                if not player_weeks.empty:
                    pts_col = "fantasy_points_ppr" if "fantasy_points_ppr" in player_weeks.columns else "fantasy_points"
                    zero_weeks = player_weeks[player_weeks[pts_col].fillna(0) < 1] if pts_col in player_weeks.columns else pd.DataFrame()
                    st.write(f"**{search_player}** — zero-point weeks from NFL data:")
                    if not zero_weeks.empty and "season" in zero_weeks.columns and "week" in zero_weeks.columns:
                        show_cols = [c for c in ["season", "week", "recent_team"] if c in zero_weeks.columns]
                        rename = {"season": "Season", "week": "Week", "recent_team": "Team"}
                        st.dataframe(
                            zero_weeks[show_cols].rename(columns=rename),
                            use_container_width=True, hide_index=True,
                        )
                    else:
                        st.info("No zero-point weeks found or insufficient data columns.")
                else:
                    st.info(f"No NFL data found for '{search_player}'.")
            except Exception as exc:
                st.warning(f"Could not load external data: {exc}")
