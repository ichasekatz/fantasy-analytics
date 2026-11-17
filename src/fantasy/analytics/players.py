"""Cross-league player fantasy performance analytics."""

from __future__ import annotations

import pandas as pd


def player_career(rosters_df: pd.DataFrame, draft_picks_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate every player's fantasy career across all leagues and seasons.

    Args:
        rosters_df: Full rosters DataFrame (all leagues).
        draft_picks_df: Full draft picks DataFrame (all leagues).

    Returns:
        DataFrame with one row per player, columns: player, position,
        total_points, starter_weeks, total_weeks, avg_per_start,
        leagues_played (count), seasons_played (count),
        times_drafted, times_kept, leagues_list (comma-separated).
        Sorted by total_points descending.
    """
    if rosters_df.empty:
        return pd.DataFrame()

    agg = (
        rosters_df.groupby(["player", "position"])
        .agg(
            total_points=("points", "sum"),
            starter_weeks=("starter", "sum"),
            total_weeks=("player", "count"),
            leagues_played=("league_id", "nunique"),
            seasons_played=("season", "nunique"),
        )
        .reset_index()
    )
    agg["avg_per_start"] = (
        agg["total_points"] / agg["starter_weeks"].replace(0, float("nan"))
    ).round(2)
    agg["total_points"] = agg["total_points"].round(2)

    leagues_list = (
        rosters_df.groupby("player")["league_id"]
        .apply(lambda s: ", ".join(sorted(s.unique())))
        .rename("leagues_list")
        .reset_index()
    )
    agg = agg.merge(leagues_list, on="player", how="left")

    if not draft_picks_df.empty:
        draft_agg = (
            draft_picks_df.groupby("player")
            .agg(times_drafted=("player", "count"), times_kept=("keeper", "sum"))
            .reset_index()
        )
        agg = agg.merge(draft_agg, on="player", how="left")
        agg["times_drafted"] = agg["times_drafted"].fillna(0).astype(int)
        agg["times_kept"] = agg["times_kept"].fillna(0).astype(int)
    else:
        agg["times_drafted"] = 0
        agg["times_kept"] = 0

    return agg.sort_values("total_points", ascending=False).reset_index(drop=True)


def player_season_breakdown(
    rosters_df: pd.DataFrame,
    draft_picks_df: pd.DataFrame,
    player: str,
) -> pd.DataFrame:
    """Season-by-season breakdown for a single player across all leagues.

    Args:
        rosters_df: Full rosters DataFrame.
        draft_picks_df: Full draft picks DataFrame.
        player: Exact player name string.

    Returns:
        DataFrame with one row per (league, season, owner), columns:
        league_id, season, owner_name, team_name, total_points, starter_weeks,
        total_weeks, avg_per_start, was_drafted, draft_round, draft_overall,
        was_keeper. Sorted by season, league_id.
    """
    r = rosters_df[rosters_df["player"] == player]
    if r.empty:
        return pd.DataFrame()

    agg = (
        r.groupby(["league_id", "season", "owner_name", "team_name"])
        .agg(
            total_points=("points", "sum"),
            starter_weeks=("starter", "sum"),
            total_weeks=("player", "count"),
        )
        .reset_index()
    )
    agg["avg_per_start"] = (
        agg["total_points"] / agg["starter_weeks"].replace(0, float("nan"))
    ).round(2)
    agg["total_points"] = agg["total_points"].round(2)

    if not draft_picks_df.empty:
        picks = draft_picks_df[draft_picks_df["player"] == player][
            ["league_id", "season", "round", "overall", "keeper"]
        ].rename(columns={"round": "draft_round", "overall": "draft_overall", "keeper": "was_keeper"})
        picks["was_drafted"] = True
        agg = agg.merge(picks, on=["league_id", "season"], how="left")
        agg["was_drafted"] = agg["was_drafted"].fillna(False)
        agg["was_keeper"] = agg["was_keeper"].fillna(False)
    else:
        agg["was_drafted"] = False
        agg["draft_round"] = pd.NA
        agg["draft_overall"] = pd.NA
        agg["was_keeper"] = False

    return agg.sort_values(["season", "league_id"]).reset_index(drop=True)


def player_weekly_scores(rosters_df: pd.DataFrame, player: str) -> pd.DataFrame:
    """Weekly fantasy scores for a player across all leagues and seasons.

    Args:
        rosters_df: Full rosters DataFrame.
        player: Exact player name string.

    Returns:
        DataFrame with columns: league_id, season, week, owner_name,
        points, starter, selected_position. Sorted by season, week.
    """
    r = rosters_df[rosters_df["player"] == player].copy()
    if r.empty:
        return pd.DataFrame()

    cols = ["league_id", "season", "week", "owner_name", "points", "starter", "selected_position"]
    return r[[c for c in cols if c in r.columns]].sort_values(["season", "week"]).reset_index(drop=True)


def cross_league_top_scorers(
    rosters_df: pd.DataFrame,
    position: str | None = None,
    season: int | None = None,
    league_id: str | None = None,
    top_n: int = 25,
) -> pd.DataFrame:
    """Top fantasy scorers with cross-league context.

    Args:
        rosters_df: Full rosters DataFrame.
        position: Filter to position, or None for all.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.
        top_n: Number of players to return.

    Returns:
        DataFrame with columns: player, position, total_points, starter_weeks,
        avg_per_start, leagues_played, seasons_played. Top N by total_points.
    """
    r = rosters_df.copy()
    if position:
        r = r[r["position"] == position]
    if season is not None:
        r = r[r["season"] == season]
    if league_id:
        r = r[r["league_id"] == league_id]

    if r.empty:
        return pd.DataFrame()

    agg = (
        r.groupby(["player", "position"])
        .agg(
            total_points=("points", "sum"),
            starter_weeks=("starter", "sum"),
            leagues_played=("league_id", "nunique"),
            seasons_played=("season", "nunique"),
        )
        .reset_index()
    )
    agg["avg_per_start"] = (
        agg["total_points"] / agg["starter_weeks"].replace(0, float("nan"))
    ).round(2)
    agg["total_points"] = agg["total_points"].round(2)

    return agg.nlargest(top_n, "total_points").reset_index(drop=True)


def players_owned_by(
    rosters_df: pd.DataFrame,
    draft_picks_df: pd.DataFrame,
    owner: str,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """All players rostered by an owner with their performance stats.

    Args:
        rosters_df: Full rosters DataFrame.
        draft_picks_df: Full draft picks DataFrame.
        owner: Owner name (exact or partial match checked externally).
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame aggregated per player/season/league with roster stats
        and draft info joined. Sorted by total_points descending.
    """
    r = rosters_df[rosters_df["owner_name"] == owner].copy()
    if season is not None:
        r = r[r["season"] == season]
    if league_id:
        r = r[r["league_id"] == league_id]
    if r.empty:
        return pd.DataFrame()

    agg = (
        r.groupby(["player", "position", "season", "league_id", "team_name"])
        .agg(
            total_points=("points", "sum"),
            starter_weeks=("starter", "sum"),
            total_weeks=("player", "count"),
        )
        .reset_index()
    )
    agg["avg_per_start"] = (
        agg["total_points"] / agg["starter_weeks"].replace(0, float("nan"))
    ).round(2)
    agg["total_points"] = agg["total_points"].round(2)

    if not draft_picks_df.empty:
        picks = draft_picks_df[draft_picks_df["owner_name"] == owner][
            ["player", "season", "league_id", "round", "overall", "keeper"]
        ].rename(columns={"round": "draft_round", "overall": "draft_overall", "keeper": "was_keeper"})
        agg = agg.merge(picks, on=["player", "season", "league_id"], how="left")
        agg["was_keeper"] = agg["was_keeper"].fillna(False)

    return agg.sort_values("total_points", ascending=False).reset_index(drop=True)
