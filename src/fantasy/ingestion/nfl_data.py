"""Fetch and cache actual NFL player stats via nfl_data_py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_cache_dir = Path(__file__).parents[4] / "data" / "external"
_weekly_cache = _cache_dir / "nfl_weekly_stats.parquet"
_seasonal_cache = _cache_dir / "nfl_seasonal_stats.parquet"

_skill_positions = {"QB", "RB", "WR", "TE", "K"}

_weekly_columns = [
    "season", "week", "player_id", "player_name", "position", "recent_team",
    "fantasy_points_ppr", "fantasy_points",
    "passing_yards", "passing_tds", "interceptions",
    "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
]

_seasonal_columns = [
    "season", "player_id", "player_name", "position", "recent_team",
    "fantasy_points_ppr", "fantasy_points",
    "passing_yards", "passing_tds", "interceptions",
    "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "games",
]


def _empty(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with the specified columns.

    Args:
        columns: Column names for the empty DataFrame.

    Returns:
        Empty DataFrame with given columns.
    """
    return pd.DataFrame(columns=columns)


def _coerce_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Keep only columns that exist in df; fill missing ones with NaN.

    Args:
        df: Source DataFrame.
        columns: Desired column list.

    Returns:
        DataFrame with exactly the requested columns.
    """
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df[columns]


def fetch_weekly_stats(seasons: list[int], force_refresh: bool = False) -> pd.DataFrame:
    """Fetch weekly NFL player stats for the given seasons.

    Uses nfl_data_py.import_weekly_data(). Results are cached as parquet.
    Returns cached data if available and force_refresh is False.

    Args:
        seasons: List of NFL seasons (years) to fetch.
        force_refresh: If True, re-fetch even if cache exists.

    Returns:
        DataFrame with columns: season, week, player_id, player_name,
        position, recent_team, fantasy_points_ppr, fantasy_points,
        passing_yards, passing_tds, interceptions, rushing_yards, rushing_tds,
        receptions, targets, receiving_yards, receiving_tds.
        Returns empty DataFrame with those columns on failure.

    Note:
        Silently returns empty DataFrame if nfl_data_py is unavailable or
        network fetch fails, so callers can degrade gracefully.
    """
    if _weekly_cache.exists() and not force_refresh:
        cached = pd.read_parquet(_weekly_cache)
        missing = [s for s in seasons if s not in cached["season"].unique()]
        if not missing:
            return cached[cached["season"].isin(seasons)]
        fetch_seasons = missing
    else:
        fetch_seasons = seasons

    parts: list[pd.DataFrame] = []
    for s in fetch_seasons:
        try:
            import nfl_data_py as nfl  # lazy import — avoids hard dependency at module load

            chunk = nfl.import_weekly_data([s])
            chunk = chunk[chunk["position"].isin(_skill_positions)].copy()
            chunk = _coerce_columns(chunk, _weekly_columns)
            parts.append(chunk)
        except Exception:
            pass  # 404 for future seasons or missing data — skip silently

    if not parts:
        if _weekly_cache.exists():
            cached = pd.read_parquet(_weekly_cache)
            return cached[cached["season"].isin(seasons)] if seasons else cached
        return _empty(_weekly_columns)

    raw = pd.concat(parts, ignore_index=True)

    _cache_dir.mkdir(parents=True, exist_ok=True)

    if _weekly_cache.exists() and not force_refresh:
        existing = pd.read_parquet(_weekly_cache)
        combined = pd.concat([existing, raw], ignore_index=True).drop_duplicates(
            subset=["season", "week", "player_id"]
        )
    else:
        combined = raw

    combined.to_parquet(_weekly_cache, index=False)
    return combined[combined["season"].isin(seasons)]


def fetch_seasonal_stats(seasons: list[int], force_refresh: bool = False) -> pd.DataFrame:
    """Fetch season-aggregate NFL player stats by aggregating weekly data.

    import_seasonal_data() lacks a position column, so we aggregate from
    fetch_weekly_stats() instead. Numeric stat columns are summed; games
    is counted as distinct weeks with any fantasy points.

    Args:
        seasons: List of NFL seasons to fetch.
        force_refresh: If True, re-fetch even if cache exists.

    Returns:
        DataFrame with season-level stats aggregated from weekly data.
        Returns empty DataFrame on failure.
    """
    if _seasonal_cache.exists() and not force_refresh:
        cached = pd.read_parquet(_seasonal_cache)
        missing = [s for s in seasons if s not in cached["season"].unique()]
        if not missing:
            return cached[cached["season"].isin(seasons)]

    weekly = fetch_weekly_stats(seasons, force_refresh=force_refresh)
    if weekly.empty:
        return _empty(_seasonal_columns)

    try:
        stat_cols = [
            "passing_yards", "passing_tds", "interceptions",
            "rushing_yards", "rushing_tds",
            "receptions", "targets", "receiving_yards", "receiving_tds",
            "fantasy_points_ppr", "fantasy_points",
        ]
        agg: dict[str, object] = {c: "sum" for c in stat_cols if c in weekly.columns}
        agg["week"] = "count"
        agg["position"] = "first"
        agg["recent_team"] = "last"
        agg["player_name"] = "first"

        raw = (
            weekly.groupby(["season", "player_id"], as_index=False)
            .agg(agg)
            .rename(columns={"week": "games"})
        )
        raw = _coerce_columns(raw, _seasonal_columns)
    except Exception:
        if _seasonal_cache.exists():
            cached = pd.read_parquet(_seasonal_cache)
            return cached[cached["season"].isin(seasons)] if seasons else cached
        return _empty(_seasonal_columns)

    _cache_dir.mkdir(parents=True, exist_ok=True)

    if _seasonal_cache.exists() and not force_refresh:
        existing = pd.read_parquet(_seasonal_cache)
        combined = pd.concat([existing, raw], ignore_index=True).drop_duplicates(
            subset=["season", "player_id"]
        )
    else:
        combined = raw

    combined.to_parquet(_seasonal_cache, index=False)
    return combined[combined["season"].isin(seasons)]


def load_weekly_stats(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load weekly stats from cache, fetching if cache is absent.

    Args:
        seasons: Seasons to load. If None, loads all cached data.

    Returns:
        Cached weekly stats DataFrame.
    """
    if not _weekly_cache.exists():
        if seasons is None:
            return _empty(_weekly_columns)
        return fetch_weekly_stats(seasons)

    df = pd.read_parquet(_weekly_cache)
    if seasons is not None:
        df = df[df["season"].isin(seasons)]
    return df


def load_seasonal_stats(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load seasonal stats from cache, fetching if cache is absent.

    Args:
        seasons: Seasons to load. If None, loads all cached data.

    Returns:
        Cached seasonal stats DataFrame.
    """
    if not _seasonal_cache.exists():
        if seasons is None:
            return _empty(_seasonal_columns)
        return fetch_seasonal_stats(seasons)

    df = pd.read_parquet(_seasonal_cache)
    if seasons is not None:
        df = df[df["season"].isin(seasons)]
    return df
