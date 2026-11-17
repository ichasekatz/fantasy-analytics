"""Draft value analytics: VORP, steals, busts, manager draft grades."""

from __future__ import annotations

import pandas as pd

# Approximate weekly PPR points for a replacement-level starter at each position.
# Replacement = last viable starter in a typical 10-12 team league.
# QB12-14 ~18 pts/wk, RB24-30 ~7.5, WR30-36 ~8.0, TE12-15 ~5.0
_replacement_baselines: dict[str, float] = {
    "QB": 18.0,
    "RB": 7.5,
    "WR": 8.0,
    "TE": 5.0,
    "K": 7.0,
    "DST": 7.0,
}

# Point-margin thresholds for steal/bust labeling
_steal_vorp_margin: float = 10.0
_bust_vorp_margin: float = -10.0


def _filter(df: pd.DataFrame, season: int | None, league_id: str | None) -> pd.DataFrame:
    """Apply season and league_id filters to a DataFrame.

    Args:
        df: Source DataFrame.
        season: Season to filter to, or None.
        league_id: League ID to filter to, or None.

    Returns:
        Filtered DataFrame.
    """
    if season is not None and "season" in df.columns:
        df = df[df["season"] == season]
    if league_id is not None and "league_id" in df.columns:
        df = df[df["league_id"] == league_id]
    return df


def player_season_points(
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Aggregate total and per-game fantasy points from roster data.

    Uses starter weeks as a "games started" proxy — weeks the player was started
    by any team in the league.

    Args:
        rosters_df: Rosters DataFrame with columns starter, points, player, position.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: season, league_id, player, position,
        total_points, starter_weeks, points_per_start.
    """
    empty_cols = ["season", "league_id", "player", "position", "total_points", "starter_weeks", "points_per_start"]
    if rosters_df.empty:
        return pd.DataFrame(columns=empty_cols)

    df = _filter(rosters_df.copy(), season, league_id)
    starters = df[df["starter"]].copy()

    if starters.empty:
        return pd.DataFrame(columns=empty_cols)

    group_cols = ["season", "league_id", "player", "position"]
    agg = (
        starters.groupby(group_cols, as_index=False)
        .agg(total_points=("points", "sum"), starter_weeks=("points", "count"))
    )
    agg["points_per_start"] = agg.apply(
        lambda r: r["total_points"] / r["starter_weeks"] if r["starter_weeks"] > 0 else 0.0,
        axis=1,
    )
    return agg[empty_cols]


def vorp(
    rosters_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Value over replacement player (VORP) for every player in a season.

    VORP = total_points - (replacement_baseline_per_week * starter_weeks)

    Positive VORP = above replacement level.

    Args:
        rosters_df: Rosters DataFrame.
        season: Season to compute VORP for.
        league_id: Filter to league, or None.

    Returns:
        DataFrame with columns: player, position, total_points, starter_weeks,
        points_per_start, replacement_baseline, vorp, season.
        Sorted by vorp descending.
    """
    empty_cols = ["player", "position", "total_points", "starter_weeks", "points_per_start",
                  "replacement_baseline", "vorp", "season"]
    pts = player_season_points(rosters_df, season=season, league_id=league_id)
    if pts.empty:
        return pd.DataFrame(columns=empty_cols)

    pts["replacement_baseline"] = pts["position"].map(_replacement_baselines).fillna(7.0)
    pts["vorp"] = pts["total_points"] - pts["replacement_baseline"] * pts["starter_weeks"]
    return pts[empty_cols].sort_values("vorp", ascending=False).reset_index(drop=True)


def _pick_value_curve(season: int) -> pd.DataFrame:
    """Load pick-value curve for a season from cache.

    Args:
        season: Season year.

    Returns:
        DataFrame with overall_pick and pick_value_index columns,
        or empty DataFrame if unavailable.
    """
    try:
        from fantasy.ingestion.external_adp import load_adp_data

        df = load_adp_data([season])
        return df[["overall_pick", "pick_value_index"]].dropna()
    except Exception:
        return pd.DataFrame(columns=["overall_pick", "pick_value_index"])


def _vorp_to_expected(pick_value_index: float, top_vorp: float) -> float:
    """Convert a pick value index (0-100) to an expected VORP estimate.

    Scales pick_value_index linearly against the observed top VORP in the season.

    Args:
        pick_value_index: Pick value index (0–100; 100 = pick 1).
        top_vorp: Observed VORP of the top player in the season.

    Returns:
        Estimated expected VORP at that pick value index.
    """
    return (pick_value_index / 100.0) * top_vorp


def draft_pick_value(
    draft_picks_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Actual value delivered for every draft pick in a season.

    Joins draft picks to player season points and VORP. Computes expected VORP
    from the pick-value curve if available.

    Args:
        draft_picks_df: Draft picks DataFrame.
        rosters_df: Rosters DataFrame.
        season: Season to analyze.
        league_id: Filter to league, or None.

    Returns:
        DataFrame with columns: overall, round, owner_name, player, position,
        keeper, total_points, points_per_start, vorp, expected_vorp,
        value_above_expected, label.
    """
    empty_cols = ["overall", "round", "owner_name", "player", "position", "keeper",
                  "total_points", "points_per_start", "vorp", "expected_vorp",
                  "value_above_expected", "label"]

    picks = _filter(draft_picks_df.copy(), season, league_id)
    if picks.empty:
        return pd.DataFrame(columns=empty_cols)

    vorp_df = vorp(rosters_df, season=season, league_id=league_id)
    pts_df = player_season_points(rosters_df, season=season, league_id=league_id)

    merged = picks.merge(
        vorp_df[["player", "vorp"]],
        on="player", how="left",
    ).merge(
        pts_df[["player", "total_points", "points_per_start"]],
        on="player", how="left",
    )

    # Attach pick-value curve
    curve = _pick_value_curve(season)
    if not curve.empty:
        top_vorp = vorp_df["vorp"].max() if not vorp_df.empty else 50.0
        curve["expected_vorp"] = curve["pick_value_index"].apply(
            lambda pvi: _vorp_to_expected(pvi, top_vorp)
        )
        merged = merged.merge(curve[["overall_pick", "expected_vorp"]].rename(
            columns={"overall_pick": "overall"}
        ), on="overall", how="left")
    else:
        # Fall back: fit expected_vorp from the season's own VORP-vs-pick polynomial
        import numpy as np
        valid = merged.dropna(subset=["vorp", "overall"])
        if len(valid) > 2:
            z = np.polyfit(valid["overall"].astype(float), valid["vorp"].astype(float), 2)
            poly = np.poly1d(z)
            merged["expected_vorp"] = merged["overall"].apply(
                lambda x: float(poly(x)) if pd.notna(x) else float("nan")
            )
        else:
            merged["expected_vorp"] = float("nan")

    merged["value_above_expected"] = merged["vorp"] - merged["expected_vorp"]

    def _label(row: pd.Series) -> str:
        vae = row.get("value_above_expected")
        if pd.isna(vae):
            return "unknown"
        if vae >= _steal_vorp_margin:
            return "steal"
        if vae <= _bust_vorp_margin:
            return "bust"
        return "fair"

    merged["label"] = merged.apply(_label, axis=1)

    keep = [c for c in empty_cols if c in merged.columns]
    out = merged[keep].copy()
    for col in empty_cols:
        if col not in out.columns:
            out[col] = float("nan") if col not in ("owner_name", "player", "position", "label") else ""
    return out[empty_cols].sort_values("overall").reset_index(drop=True)


def manager_draft_grades(
    draft_picks_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Season-level draft grades per manager.

    Aggregates draft_pick_value() across all picks for each manager.

    Args:
        draft_picks_df: Draft picks DataFrame.
        rosters_df: Rosters DataFrame.
        season: Filter to season, or None for all seasons.
        league_id: Filter to league, or None.

    Returns:
        DataFrame with columns: season, owner_name, total_draft_vorp,
        avg_pick_vorp, steals_count, busts_count, keeper_count,
        non_keeper_vorp, draft_rank.
    """
    empty_cols = ["season", "owner_name", "total_draft_vorp", "avg_pick_vorp",
                  "steals_count", "busts_count", "keeper_count", "non_keeper_vorp", "draft_rank"]

    picks_df = _filter(draft_picks_df.copy(), season, league_id)
    if picks_df.empty:
        return pd.DataFrame(columns=empty_cols)

    seasons = sorted(picks_df["season"].unique())
    rows = []
    for s in seasons:
        dpv = draft_pick_value(draft_picks_df, rosters_df, season=s, league_id=league_id)
        if dpv.empty:
            continue
        for owner, grp in dpv.groupby("owner_name"):
            non_keepers = grp[~grp["keeper"]]
            rows.append({
                "season": s,
                "owner_name": owner,
                "total_draft_vorp": non_keepers["vorp"].sum(skipna=True),
                "avg_pick_vorp": non_keepers["vorp"].mean(skipna=True),
                "steals_count": int((non_keepers["label"] == "steal").sum()),
                "busts_count": int((non_keepers["label"] == "bust").sum()),
                "keeper_count": int(grp["keeper"].sum()),
                "non_keeper_vorp": non_keepers["vorp"].sum(skipna=True),
            })

    if not rows:
        return pd.DataFrame(columns=empty_cols)

    result = pd.DataFrame(rows)
    result["draft_rank"] = result.groupby("season")["total_draft_vorp"].rank(
        ascending=False, method="min"
    ).astype(int)
    return result[empty_cols].sort_values(["season", "draft_rank"]).reset_index(drop=True)


def best_picks_ever(
    draft_picks_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    league_id: str | None = None,
    top_n: int = 25,
    adp_adjusted: bool = False,
) -> pd.DataFrame:
    """Top N best draft picks in league history by VORP.

    Args:
        draft_picks_df: Draft picks DataFrame.
        rosters_df: Rosters DataFrame.
        league_id: Filter to league, or None for all.
        top_n: Number of picks to return.

    Returns:
        DataFrame of top_n picks sorted by vorp descending, plus rank column.
    """
    picks = _filter(draft_picks_df.copy(), None, league_id)
    seasons = sorted(picks["season"].unique())
    all_rows = []
    for s in seasons:
        dpv = draft_pick_value(draft_picks_df, rosters_df, season=s, league_id=league_id)
        if not dpv.empty:
            dpv["season"] = s
            all_rows.append(dpv)

    if not all_rows:
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    if adp_adjusted and "value_above_expected" in combined.columns:
        combined = combined.dropna(subset=["value_above_expected"]).sort_values("value_above_expected", ascending=False)
    else:
        combined = combined.sort_values("vorp", ascending=False)
    combined = combined.head(top_n).reset_index(drop=True)
    combined["rank"] = combined.index + 1
    return combined


def worst_picks_ever(
    draft_picks_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    league_id: str | None = None,
    top_n: int = 25,
    adp_adjusted: bool = False,
) -> pd.DataFrame:
    """Top N worst draft picks (biggest busts) in league history by VORP.

    Excludes keeper picks — a low VORP keeper is not a scouting failure.

    Args:
        draft_picks_df: Draft picks DataFrame.
        rosters_df: Rosters DataFrame.
        league_id: Filter to league, or None for all.
        top_n: Number of picks to return.

    Returns:
        DataFrame of top_n picks sorted by vorp ascending (worst first), plus rank.
    """
    picks = _filter(draft_picks_df.copy(), None, league_id)
    seasons = sorted(picks["season"].unique())
    all_rows = []
    for s in seasons:
        dpv = draft_pick_value(draft_picks_df, rosters_df, season=s, league_id=league_id)
        if not dpv.empty:
            dpv["season"] = s
            all_rows.append(dpv)

    if not all_rows:
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined[~combined["keeper"]].copy()
    if adp_adjusted and "value_above_expected" in combined.columns:
        combined = combined.dropna(subset=["value_above_expected"]).sort_values("value_above_expected", ascending=True)
    else:
        combined = combined.sort_values("vorp", ascending=True)
    combined = combined.head(top_n).reset_index(drop=True)
    combined["rank"] = combined.index + 1
    return combined
