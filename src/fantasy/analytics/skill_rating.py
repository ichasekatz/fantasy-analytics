"""Multi-dimensional manager skill rating."""

from __future__ import annotations

import numpy as np
import pandas as pd

# Composite weight for each dimension
_weight_performance: float = 0.40
_weight_consistency: float = 0.20
_weight_luck_adjusted: float = 0.25
_weight_lineup: float = 0.15

# Minimum seasons before a sample is considered reliable
_min_seasons_for_reliable_estimate: int = 3


def _all_play_win_pct(
    matchups_df: pd.DataFrame,
    owners: list[str],
    seasons: list[int],
) -> dict[str, float]:
    """Compute all-play win percentage per owner across given seasons.

    For each week, counts the fraction of other teams each owner outscored.

    Args:
        matchups_df: Regular-season matchups DataFrame (already filtered).
        owners: Distinct owners to include.
        seasons: Seasons to include.

    Returns:
        Dict mapping owner → all-play win percentage (0–1).
    """
    totals: dict[str, list[float]] = {o: [] for o in owners}

    for season in seasons:
        season_df = matchups_df[matchups_df["season"] == season]
        weeks = season_df["week"].unique()
        for week in weeks:
            week_df = season_df[season_df["week"] == week]
            # Build {owner: score} for this week
            week_scores: dict[str, float] = {}
            for _, row in week_df.iterrows():
                week_scores[row["team_a_owner"]] = float(row["points_a"])
                week_scores[row["team_b_owner"]] = float(row["points_b"])

            n = len(week_scores)
            if n < 2:
                continue
            for owner, score in week_scores.items():
                if owner not in totals:
                    continue
                beaten = sum(1 for o2, s2 in week_scores.items() if o2 != owner and score > s2)
                totals[owner].append(beaten / (n - 1))

    return {o: float(np.mean(v)) if v else 0.0 for o, v in totals.items()}


def _regular_season_matchups(
    matchups_df: pd.DataFrame,
    season: int | None,
    league_id: str | None,
) -> pd.DataFrame:
    """Return filtered regular-season matchups.

    Args:
        matchups_df: Full matchups DataFrame.
        season: Season to keep, or None for all.
        league_id: League to keep, or None for all.

    Returns:
        Filtered copy.
    """
    df = matchups_df.copy()
    if season is not None:
        df = df[df["season"] == season]
    if league_id is not None:
        df = df[df["league_id"] == league_id]
    if "is_playoff" in df.columns:
        df = df[~df["is_playoff"].fillna(False)]
    return df


def _to_percentile_scores(values: pd.Series) -> pd.Series:
    """Convert a series of numeric values to percentile scores (0–100).

    Args:
        values: Numeric series, may contain NaN.

    Returns:
        Percentile series (0–100); NaN inputs remain NaN.
    """
    return values.rank(pct=True, na_option="keep") * 100


def compute_skill_ratings(
    matchups_df: pd.DataFrame,
    luck_df: pd.DataFrame | None = None,
    lineup_df: pd.DataFrame | None = None,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Multi-dimensional manager skill rating.

    Computes separate dimension scores then a composite. Each dimension is
    percentile-ranked (0–100) across all managers in the filtered sample.

    Dimensions:
        - performance_score: All-play win percentage (schedule-independent).
        - consistency_score: Inverse of coefficient of variation of weekly scores.
          Higher = more consistent scoring.
        - longevity_score: Number of seasons played, normalized to 0–100.
        - luck_adjusted_score: All-play win% with expected wins offset subtracted.
          Requires luck_df with columns 'owner', 'expected_wins', 'actual_wins'.
        - lineup_score: Average lineup efficiency (0–1 scale → percentile).
          Requires lineup_df with columns 'owner', 'avg_efficiency'.

    Composite weights:
        performance: 0.40, consistency: 0.20, luck_adjusted: 0.25, lineup: 0.15.
        If luck_adjusted is unavailable, its weight transfers to performance.
        If lineup is unavailable, its weight is zeroed and others renormalized.

    Args:
        matchups_df: Matchups DataFrame (required).
        luck_df: Output of luck.luck_metrics() with 'owner', 'expected_wins',
            'actual_wins' columns, or None.
        lineup_df: Output of lineups.lineup_efficiency_summary() with 'owner',
            'avg_efficiency' columns, or None.
        season: Filter to season, or None for all-time.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: owner, performance_score, consistency_score,
        longevity_score, luck_adjusted_score, lineup_score, composite_score,
        composite_rank, seasons_played, low_sample_warning.
        Sorted by composite_score descending.

    Note:
        composite_score is a percentile (0–100) for readability.
        low_sample_warning is True when seasons_played < 3.
    """
    empty = pd.DataFrame(
        columns=["owner", "performance_score", "consistency_score", "longevity_score",
                 "luck_adjusted_score", "lineup_score", "composite_score",
                 "composite_rank", "seasons_played", "low_sample_warning"]
    )
    rs = _regular_season_matchups(matchups_df, season, league_id)
    if rs.empty:
        return empty

    # Collect all owners and seasons
    all_owners: list[str] = list(
        set(rs["team_a_owner"].tolist()) | set(rs["team_b_owner"].tolist())
    )
    seasons_list = sorted(rs["season"].unique().tolist())

    # Seasons played per owner
    owner_seasons: dict[str, int] = {}
    for owner in all_owners:
        played = rs[(rs["team_a_owner"] == owner) | (rs["team_b_owner"] == owner)]["season"].nunique()
        owner_seasons[owner] = int(played)

    # --- Dimension 1: performance_score (all-play win%) ---
    ap_pct = _all_play_win_pct(rs, all_owners, seasons_list)

    # --- Dimension 2: consistency_score (inverse CV of weekly scores) ---
    # Build owner → list of weekly scores
    weekly_scores: dict[str, list[float]] = {o: [] for o in all_owners}
    for _, row in rs.iterrows():
        weekly_scores[row["team_a_owner"]].append(float(row["points_a"]))
        weekly_scores[row["team_b_owner"]].append(float(row["points_b"]))

    consistency_raw: dict[str, float] = {}
    for owner in all_owners:
        scores = weekly_scores[owner]
        if len(scores) < 2:
            consistency_raw[owner] = np.nan
            continue
        mean = np.mean(scores)
        std = np.std(scores, ddof=1)
        cv = std / mean if mean > 0 else np.nan
        # Inverse CV: higher is more consistent; cap to avoid infinity
        consistency_raw[owner] = 1.0 / cv if cv and cv > 0 else np.nan

    # --- Build base DataFrame ---
    rows = []
    for owner in all_owners:
        rows.append({
            "owner": owner,
            "_ap_pct": ap_pct.get(owner, 0.0),
            "_consistency_raw": consistency_raw.get(owner, np.nan),
            "seasons_played": owner_seasons.get(owner, 0),
        })
    df = pd.DataFrame(rows)

    # Percentile-rank each raw dimension
    df["performance_score"] = _to_percentile_scores(pd.Series(df["_ap_pct"].values))
    df["consistency_score"] = _to_percentile_scores(pd.Series(df["_consistency_raw"].values))
    df["longevity_score"] = _to_percentile_scores(pd.Series(df["seasons_played"].astype(float).values))

    # --- Dimension 4: luck_adjusted_score ---
    if luck_df is not None and not luck_df.empty and {"owner", "expected_wins", "actual_wins"}.issubset(luck_df.columns):
        luck_map = luck_df.set_index("owner")[["actual_wins", "expected_wins"]]
        df["_luck_delta"] = df["owner"].map(lambda o: (
            float(luck_map.loc[o, "actual_wins"]) - float(luck_map.loc[o, "expected_wins"])
            if o in luck_map.index else np.nan
        ))
        # Luck-adjusted performance = ap_pct penalized for luck delta
        # Subtract normalized luck delta from ap_pct to get "true" performance
        df["_luck_adj_raw"] = df["_ap_pct"] - df["_luck_delta"].fillna(0.0) * 0.05
        df["luck_adjusted_score"] = _to_percentile_scores(df["_luck_adj_raw"])
    else:
        df["luck_adjusted_score"] = np.nan

    # --- Dimension 5: lineup_score ---
    if lineup_df is not None and not lineup_df.empty and {"owner", "avg_efficiency"}.issubset(lineup_df.columns):
        lineup_map = lineup_df.set_index("owner")["avg_efficiency"]
        df["_lineup_raw"] = df["owner"].map(lambda o: float(lineup_map.loc[o]) if o in lineup_map.index else np.nan)
        df["lineup_score"] = _to_percentile_scores(df["_lineup_raw"])
    else:
        df["lineup_score"] = np.nan

    # --- Composite ---
    has_luck = df["luck_adjusted_score"].notna().any()
    has_lineup = df["lineup_score"].notna().any()

    w_perf = _weight_performance + (0.0 if has_luck else _weight_luck_adjusted)
    w_cons = _weight_consistency
    w_luck = _weight_luck_adjusted if has_luck else 0.0
    w_line = _weight_lineup if has_lineup else 0.0
    total_w = w_perf + w_cons + w_luck + w_line
    if total_w == 0:
        total_w = 1.0

    df["_composite_raw"] = (
        df["performance_score"] * w_perf
        + df["consistency_score"] * w_cons
        + df["luck_adjusted_score"].fillna(df["performance_score"]) * w_luck
        + df["lineup_score"].fillna(0.0) * w_line
    ) / total_w

    df["composite_score"] = _to_percentile_scores(df["_composite_raw"])
    df["composite_rank"] = df["composite_score"].rank(ascending=False, method="min").astype(int)
    df["low_sample_warning"] = df["seasons_played"] < _min_seasons_for_reliable_estimate

    # Drop internal columns
    drop_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=drop_cols)

    return df.sort_values("composite_score", ascending=False).reset_index(drop=True)
