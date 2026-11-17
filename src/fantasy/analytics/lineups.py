"""Lineup efficiency analytics from weekly roster data."""

from __future__ import annotations

import pandas as pd

# Positions eligible to fill a FLEX slot
_flex_eligible: set[str] = {"RB", "WR", "TE"}


def _filter_rosters(
    rosters_df: pd.DataFrame,
    season: int | None,
    league_id: str | None,
) -> pd.DataFrame:
    """Apply season and league filters to a rosters DataFrame.

    Args:
        rosters_df: Rosters DataFrame.
        season: Season to keep, or None for all.
        league_id: League to keep, or None for all.

    Returns:
        Filtered copy.
    """
    out = rosters_df.copy()
    if season is not None:
        out = out[out["season"] == season]
    if league_id is not None:
        out = out[out["league_id"] == league_id]
    return out


def _optimal_lineup_points(group: pd.DataFrame) -> float:
    """Compute optimal legal lineup points for one team/week group.

    Algorithm:
    1. Count required non-BN, non-FLEX slots from selected_position values.
    2. Fill each positional slot greedily (best-scoring eligible player).
    3. Fill FLEX slot with best remaining FLEX-eligible player.

    Args:
        group: Rows for one team in one week.

    Returns:
        Total points from the optimal legal starting lineup.
    """
    players = group[["position", "points", "selected_position"]].copy()
    players = players.sort_values("points", ascending=False)

    # Count slots needed per position (excluding BN)
    starters = players[players["selected_position"] != "BN"]
    slot_counts: dict[str, int] = {}
    has_flex = False
    for pos in starters["selected_position"]:
        if pos == "FLEX":
            has_flex = True
        else:
            slot_counts[pos] = slot_counts.get(pos, 0) + 1

    used_indices: set[int] = set()
    total = 0.0

    # Fill non-FLEX positional slots greedily
    for pos, count in slot_counts.items():
        eligible = players[(players["position"] == pos) & (~players.index.isin(used_indices))]
        for idx, row in eligible.head(count).iterrows():
            total += row["points"] if pd.notna(row["points"]) else 0.0
            used_indices.add(idx)

    # Fill FLEX slot with best remaining FLEX-eligible player
    if has_flex:
        remaining = players[
            (players["position"].isin(_flex_eligible)) & (~players.index.isin(used_indices))
        ]
        if not remaining.empty:
            best = remaining.iloc[0]
            total += best["points"] if pd.notna(best["points"]) else 0.0

    return total


def lineup_efficiency(
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Lineup efficiency: actual starter points vs optimal possible lineup.

    For each team/week, computes the best legal lineup by assigning players
    to their valid position slots to maximize points, then compares to actual.

    Args:
        rosters_df: Rosters DataFrame with columns: league_id, season, week,
            team_id, team_name, owner_name, position, selected_position,
            starter, points.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: league_id, season, week, owner, team_name,
        actual_points, optimal_points, efficiency, points_left_on_bench.
    """
    empty = pd.DataFrame(
        columns=["league_id", "season", "week", "owner", "team_name",
                 "actual_points", "optimal_points", "efficiency", "points_left_on_bench"]
    )
    df = _filter_rosters(rosters_df, season, league_id)
    if df.empty:
        return empty

    group_keys = ["league_id", "season", "week", "team_id", "team_name", "owner_name"]

    actual = (
        df[df["starter"] == True]  # noqa: E712
        .groupby(group_keys)["points"]
        .sum()
        .rename("actual_points")
        .reset_index()
    )

    optimal_rows = []
    for keys, group in df.groupby(group_keys):
        opt = _optimal_lineup_points(group)
        optimal_rows.append({k: v for k, v in zip(group_keys, keys)} | {"optimal_points": opt})
    optimal = pd.DataFrame(optimal_rows)

    merged = actual.merge(optimal, on=group_keys, how="outer")
    merged["actual_points"] = merged["actual_points"].fillna(0.0)
    merged["optimal_points"] = merged["optimal_points"].fillna(0.0)
    merged["efficiency"] = (
        (merged["actual_points"] / merged["optimal_points"])
        .clip(upper=1.0)
        .where(merged["optimal_points"] > 0, other=1.0)
    )
    merged["points_left_on_bench"] = (merged["optimal_points"] - merged["actual_points"]).clip(lower=0.0)
    merged = merged.rename(columns={"owner_name": "owner"})
    return merged[["league_id", "season", "week", "owner", "team_name",
                   "actual_points", "optimal_points", "efficiency", "points_left_on_bench"]]


def lineup_efficiency_summary(
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Season-level lineup efficiency summary per manager.

    Aggregates lineup_efficiency() across all weeks for each manager.

    Args:
        rosters_df: Rosters DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: owner, avg_efficiency, avg_points_left,
        total_points_left, worst_week_left, best_week_left, seasons.
    """
    empty = pd.DataFrame(
        columns=["owner", "avg_efficiency", "avg_points_left",
                 "total_points_left", "worst_week_left", "best_week_left", "seasons"]
    )
    eff = lineup_efficiency(rosters_df, season, league_id)
    if eff.empty:
        return empty

    seasons_played = eff.groupby("owner")["season"].nunique().rename("seasons")
    agg = eff.groupby("owner").agg(
        avg_efficiency=("efficiency", "mean"),
        avg_points_left=("points_left_on_bench", "mean"),
        total_points_left=("points_left_on_bench", "sum"),
        worst_week_left=("points_left_on_bench", "max"),
        best_week_left=("points_left_on_bench", "min"),
    ).reset_index()
    return agg.join(seasons_played, on="owner").reset_index(drop=True)


def lineup_decision_quality(
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Per manager-week: actual score, optimal score, missed points, and letter grade.

    Returns:
        DataFrame with columns: league_id, season, week, owner, team_name,
        actual_score, optimal_score, missed_points, missed_pct, num_starters, decision_grade.
    """
    empty = pd.DataFrame(
        columns=["league_id", "season", "week", "owner", "team_name",
                 "actual_score", "optimal_score", "missed_points", "missed_pct",
                 "num_starters", "decision_grade"]
    )
    eff = lineup_efficiency(rosters_df, season, league_id)
    if eff.empty:
        return empty

    df = eff.rename(columns={
        "actual_points": "actual_score",
        "optimal_points": "optimal_score",
        "points_left_on_bench": "missed_points",
    }).copy()

    df["missed_pct"] = (
        (df["missed_points"] / df["optimal_score"])
        .where(df["optimal_score"] > 0, other=0.0)
        .round(3)
    )

    starters_count = (
        rosters_df[rosters_df["starter"] == True]  # noqa: E712
        .groupby(["league_id", "season", "week", "owner_name"])
        .size()
        .rename("num_starters")
        .reset_index()
        .rename(columns={"owner_name": "owner"})
    )
    df = df.merge(starters_count, on=["league_id", "season", "week", "owner"], how="left")
    df["num_starters"] = df["num_starters"].fillna(0).astype(int)

    def _grade(missed: float) -> str:
        if missed < 5:
            return "A"
        if missed < 15:
            return "B"
        if missed < 30:
            return "C"
        return "D"

    df["decision_grade"] = df["missed_points"].apply(_grade)
    return df[["league_id", "season", "week", "owner", "team_name",
               "actual_score", "optimal_score", "missed_points", "missed_pct",
               "num_starters", "decision_grade"]]


def bench_strength(
    rosters_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Points scored by bench players vs starters, per team per week.

    Args:
        rosters_df: Rosters DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: season, week, owner, bench_points,
        starter_points, bench_ratio (bench / starter).
    """
    empty = pd.DataFrame(
        columns=["season", "week", "owner", "bench_points", "starter_points", "bench_ratio"]
    )
    df = _filter_rosters(rosters_df, season, league_id)
    if df.empty:
        return empty

    df = df.rename(columns={"owner_name": "owner"})
    bench = (
        df[df["selected_position"] == "BN"]
        .groupby(["season", "week", "owner"])["points"]
        .sum()
        .rename("bench_points")
        .reset_index()
    )
    starters = (
        df[df["starter"] == True]  # noqa: E712
        .groupby(["season", "week", "owner"])["points"]
        .sum()
        .rename("starter_points")
        .reset_index()
    )
    merged = bench.merge(starters, on=["season", "week", "owner"], how="outer").fillna(0.0)
    merged["bench_ratio"] = (
        (merged["bench_points"] / merged["starter_points"])
        .where(merged["starter_points"] > 0, other=0.0)
    )
    return merged
