"""Fetch and cache historical ADP / draft-value data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_cache_dir = Path(__file__).parents[4] / "data" / "external"
_adp_cache = _cache_dir / "historical_adp.parquet"

_adp_columns = ["season", "overall_pick", "pick_value_index", "source"]


def fetch_adp_data(seasons: list[int], force_refresh: bool = False) -> pd.DataFrame:
    """Fetch historical average draft position data.

    Primary source: nfl_data_py.import_draft_values() for pick value curves.
    This gives expected value by draft slot, usable as ADP baseline.

    For actual historical fantasy ADP by player, we construct an estimate:
    Given that exact historical ADP snapshots are not freely available via API,
    this function returns pick-slot expected value data (value over replacement
    by draft position) rather than fabricating per-player ADP.

    Args:
        seasons: Seasons to fetch data for.
        force_refresh: If True, ignore cache.

    Returns:
        DataFrame with columns: season, overall_pick, pick_value_index
        (expected fantasy value index by pick, normalized to 100 at pick 1),
        source ('nfl_data_py_draft_values').
        Returns empty DataFrame on failure.

    Note:
        True historical per-player ADP requires paid sources (FantasyPros premium,
        platform APIs). This provides pick-value baseline only. The source column
        documents this. Never fabricate per-player ADP values.
    """
    if _adp_cache.exists() and not force_refresh:
        cached = pd.read_parquet(_adp_cache)
        missing = [s for s in seasons if s not in cached["season"].unique()]
        if not missing:
            return cached[cached["season"].isin(seasons)]

    rows: list[dict] = []

    # Attempt nfl_data_py draft values (pick-slot value curve)
    try:
        import nfl_data_py as nfl  # lazy import

        raw = nfl.import_draft_values()
        # import_draft_values returns: pick, value (Stuart, Johnson, etc.)
        # Use the mean of available value columns as pick_value_index
        value_cols = [c for c in raw.columns if c not in ("pick",)]
        raw["pick_value_index"] = raw[value_cols].mean(axis=1)
        # Normalize to 100 at pick 1
        max_val = raw["pick_value_index"].max()
        if max_val > 0:
            raw["pick_value_index"] = (raw["pick_value_index"] / max_val) * 100.0

        for season in seasons:
            season_rows = raw[["pick", "pick_value_index"]].copy()
            season_rows = season_rows.rename(columns={"pick": "overall_pick"})
            season_rows["season"] = season
            season_rows["source"] = "nfl_data_py_draft_values"
            rows.append(season_rows)
    except Exception:
        # Fall back to a simple hyperbolic decay curve: value ∝ 1 / sqrt(pick)
        # This is a rough empirical approximation, clearly labeled
        for season in seasons:
            import numpy as np

            picks = range(1, 201)
            values = [100.0 / (pick**0.5) for pick in picks]
            max_v = values[0]
            season_rows = pd.DataFrame({
                "overall_pick": list(picks),
                "pick_value_index": [v / max_v * 100.0 for v in values],
                "season": season,
                "source": "hyperbolic_fallback_1/sqrt(pick)",
            })
            rows.append(season_rows)

    if not rows:
        return pd.DataFrame(columns=_adp_columns)

    combined = pd.concat(rows, ignore_index=True)[_adp_columns]

    _cache_dir.mkdir(parents=True, exist_ok=True)

    if _adp_cache.exists() and not force_refresh:
        existing = pd.read_parquet(_adp_cache)
        combined = pd.concat([existing, combined], ignore_index=True).drop_duplicates(
            subset=["season", "overall_pick"]
        )

    combined.to_parquet(_adp_cache, index=False)
    return combined[combined["season"].isin(seasons)]


def load_adp_data(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load ADP/draft value data from cache, fetching if absent.

    Args:
        seasons: Seasons to load, or None for all cached.

    Returns:
        Draft value DataFrame.
    """
    if not _adp_cache.exists():
        if seasons is None:
            return pd.DataFrame(columns=_adp_columns)
        return fetch_adp_data(seasons)

    df = pd.read_parquet(_adp_cache)
    if seasons is not None:
        df = df[df["season"].isin(seasons)]
    return df


def adp_data_inventory() -> dict[str, str]:
    """Report what ADP data is available and from what sources.

    Returns:
        Dict mapping metric name to availability description string.
    """
    pick_curve_status = "AVAILABLE via nfl_data_py (cached)" if _adp_cache.exists() else "NOT YET FETCHED"
    return {
        "per_player_adp": (
            "NOT AVAILABLE — requires paid source (FantasyPros premium API, "
            "ESPN/Sleeper historical ADP exports). No free programmatic source "
            "provides true historical pre-season snapshots."
        ),
        "pick_value_curve": pick_curve_status,
        "pick_value_source": (
            "nfl_data_py import_draft_values() — historical pick trade-value curves "
            "(Stuart, Johnson models). Normalized to 100 at pick 1. "
            "Fallback: hyperbolic 1/sqrt(pick) decay if nfl_data_py unavailable."
        ),
    }
