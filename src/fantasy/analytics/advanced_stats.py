"""Advanced manager statistics derived from matchup data."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _filter(
    df: pd.DataFrame,
    season: int | None,
    league_id: str | None,
    include_playoffs: bool,
) -> pd.DataFrame:
    """Apply season, league, and playoff filters.

    Args:
        df: Matchups DataFrame.
        season: Season to keep, or None for all.
        league_id: League to keep, or None for all.
        include_playoffs: If False, drop is_playoff == True rows.

    Returns:
        Filtered DataFrame (copy).
    """
    out = df.copy()
    if season is not None:
        out = out[out["season"] == season]
    if league_id is not None:
        out = out[out["league_id"] == league_id]
    if not include_playoffs:
        if "is_playoff" in out.columns:
            out = out[~out["is_playoff"].fillna(False)]
    return out


def _long_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot matchups to one row per team per game with winner flag.

    Args:
        df: Filtered matchups DataFrame.

    Returns:
        DataFrame with columns: week, owner, points, opponent_points,
        won, margin, league_id, season.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["week", "owner", "points", "opponent_points", "won", "margin", "league_id", "season"]
        )
    side_a = df[["league_id", "season", "week", "team_a_owner", "points_a", "points_b", "winner_team_id", "team_a_id"]].copy()
    side_a = side_a.rename(columns={"team_a_owner": "owner", "points_a": "points", "points_b": "opponent_points", "team_a_id": "team_id"})
    side_a["won"] = side_a["winner_team_id"] == side_a["team_id"]

    side_b = df[["league_id", "season", "week", "team_b_owner", "points_b", "points_a", "winner_team_id", "team_b_id"]].copy()
    side_b = side_b.rename(columns={"team_b_owner": "owner", "points_b": "points", "points_a": "opponent_points", "team_b_id": "team_id"})
    side_b["won"] = side_b["winner_team_id"] == side_b["team_id"]

    out = pd.concat([side_a, side_b], ignore_index=True)
    out["margin"] = (out["points"] - out["opponent_points"]).abs()
    return out.drop(columns=["winner_team_id", "team_id"])


def close_game_record(
    matchups_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
    threshold: float = 10.0,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Win/loss record in close games (margin <= threshold points).

    Args:
        matchups_df: Matchups DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.
        threshold: Point margin defining a close game (default 10.0).
        include_playoffs: Include playoff weeks (default False).

    Returns:
        DataFrame with columns: owner, close_wins, close_losses, close_pct.
    """
    empty = pd.DataFrame(columns=["owner", "close_wins", "close_losses", "close_pct"])
    df = _filter(matchups_df, season, league_id, include_playoffs)
    long = _long_scores(df)
    if long.empty:
        return empty

    close = long[long["margin"] <= threshold]
    if close.empty:
        return empty

    agg = (
        close.groupby("owner")["won"]
        .agg(close_wins="sum", close_losses=lambda x: (~x).sum())
        .reset_index()
    )
    total = agg["close_wins"] + agg["close_losses"]
    agg["close_pct"] = np.where(total > 0, agg["close_wins"] / total, 0.0)
    return agg


def blowout_record(
    matchups_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
    threshold: float = 30.0,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Win/loss record in blowout games (margin >= threshold points).

    Args:
        matchups_df: Matchups DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.
        threshold: Margin defining a blowout (default 30.0).
        include_playoffs: Include playoff weeks (default False).

    Returns:
        DataFrame with columns: owner, blowout_wins, blowout_losses.
    """
    empty = pd.DataFrame(columns=["owner", "blowout_wins", "blowout_losses"])
    df = _filter(matchups_df, season, league_id, include_playoffs)
    long = _long_scores(df)
    if long.empty:
        return empty

    blowouts = long[long["margin"] >= threshold]
    if blowouts.empty:
        return empty

    return (
        blowouts.groupby("owner")["won"]
        .agg(blowout_wins="sum", blowout_losses=lambda x: (~x).sum())
        .reset_index()
    )


def scoring_volatility(
    matchups_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Standard deviation and coefficient of variation of weekly scores.

    Args:
        matchups_df: Matchups DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.
        include_playoffs: Include playoff weeks (default False).

    Returns:
        DataFrame with columns: owner, mean_score, std_score, cv_score,
        median_score, high_score, low_score, seasons_played.
    """
    empty = pd.DataFrame(
        columns=["owner", "mean_score", "std_score", "cv_score", "median_score", "high_score", "low_score", "seasons_played"]
    )
    df = _filter(matchups_df, season, league_id, include_playoffs)
    long = _long_scores(df)
    if long.empty:
        return empty

    seasons_played = long.groupby("owner")["season"].nunique().rename("seasons_played")
    agg = long.groupby("owner")["points"].agg(
        mean_score="mean",
        std_score="std",
        median_score="median",
        high_score="max",
        low_score="min",
    ).reset_index()
    agg = agg.join(seasons_played, on="owner")
    agg["cv_score"] = np.where(agg["mean_score"] > 0, agg["std_score"] / agg["mean_score"], np.nan)
    return agg


def weekly_scoring_percentile(
    matchups_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Each team's weekly score as a percentile within the league that week.

    Args:
        matchups_df: Matchups DataFrame.
        season: Season to analyze (required).
        league_id: Filter to league, or None for all.
        include_playoffs: Include playoff weeks (default False).

    Returns:
        DataFrame with columns: week, owner, points, percentile (0–100).
    """
    empty = pd.DataFrame(columns=["week", "owner", "points", "percentile"])
    df = _filter(matchups_df, season, league_id, include_playoffs)
    long = _long_scores(df)
    if long.empty:
        return empty

    def _pct(group: pd.Series) -> pd.Series:
        """Compute percentile rank within a weekly group."""
        return group.rank(pct=True) * 100

    long["percentile"] = long.groupby("week")["points"].transform(_pct)
    return long[["week", "owner", "points", "percentile"]].reset_index(drop=True)


def opponent_scoring_percentile(
    matchups_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
    include_playoffs: bool = False,
) -> pd.DataFrame:
    """Average percentile rank of opponents each manager faced.

    Higher value means tougher schedule (opponents scored in higher percentiles).

    Args:
        matchups_df: Matchups DataFrame.
        season: Season to analyze (required).
        league_id: Filter to league, or None for all.
        include_playoffs: Include playoff weeks (default False).

    Returns:
        DataFrame with columns: owner, avg_opp_percentile.
    """
    empty = pd.DataFrame(columns=["owner", "avg_opp_percentile"])
    df = _filter(matchups_df, season, league_id, include_playoffs)
    long = _long_scores(df)
    if long.empty:
        return empty

    # Compute each score's league-wide weekly percentile, then attach to opponent side
    def _pct(group: pd.Series) -> pd.Series:
        """Compute percentile rank within a weekly group."""
        return group.rank(pct=True) * 100

    long["opp_pct"] = long.groupby("week")["opponent_points"].transform(_pct)
    return (
        long.groupby("owner")["opp_pct"]
        .mean()
        .rename("avg_opp_percentile")
        .reset_index()
    )
