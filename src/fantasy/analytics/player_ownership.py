"""Player ownership history and career statistics across the league."""

from __future__ import annotations

import pandas as pd


def player_ownership_history(rosters_df: pd.DataFrame, draft_df: pd.DataFrame) -> pd.DataFrame:
    empty_cols = ["player", "position", "season", "league_id", "owner_name",
                  "total_points", "started_points", "weeks_owned", "weeks_started", "was_drafted"]
    if rosters_df.empty:
        return pd.DataFrame(columns=empty_cols)

    df = rosters_df.copy()
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0.0)

    group_cols = ["player", "position", "season", "league_id", "owner_name"]
    agg = df.groupby(group_cols, as_index=False).agg(
        total_points=("points", "sum"),
        weeks_owned=("points", "count"),
    )

    starters = df[df["starter"] == True].groupby(group_cols, as_index=False).agg(
        started_points=("points", "sum"),
        weeks_started=("points", "count"),
    )

    result = agg.merge(starters, on=group_cols, how="left")
    result["started_points"] = result["started_points"].fillna(0.0)
    result["weeks_started"] = result["weeks_started"].fillna(0).astype(int)

    if not draft_df.empty and "player" in draft_df.columns:
        drafted_set = set(
            zip(draft_df["player"].fillna(""), draft_df["season"].fillna(0), draft_df.get("league_id", pd.Series([""] * len(draft_df))).fillna(""))
        )
        result["was_drafted"] = result.apply(
            lambda r: (r["player"], r["season"], r.get("league_id", "")) in drafted_set, axis=1
        )
    else:
        result["was_drafted"] = False

    return result[empty_cols].sort_values(["player", "season"]).reset_index(drop=True)


def player_career_stats(rosters_df: pd.DataFrame, draft_df: pd.DataFrame) -> pd.DataFrame:
    empty_cols = ["player", "position", "total_managers", "total_seasons",
                  "total_started_points", "total_roster_points",
                  "best_owner", "best_owner_points", "times_drafted", "most_recent_season"]
    if rosters_df.empty:
        return pd.DataFrame(columns=empty_cols)

    history = player_ownership_history(rosters_df, draft_df)
    if history.empty:
        return pd.DataFrame(columns=empty_cols)

    agg = history.groupby(["player", "position"], as_index=False).agg(
        total_managers=("owner_name", "nunique"),
        total_seasons=("season", "nunique"),
        total_started_points=("started_points", "sum"),
        total_roster_points=("total_points", "sum"),
        most_recent_season=("season", "max"),
    )

    best = (
        history.groupby(["player", "owner_name"], as_index=False)["started_points"]
        .sum()
        .sort_values("started_points", ascending=False)
        .groupby("player", as_index=False)
        .first()
        .rename(columns={"owner_name": "best_owner", "started_points": "best_owner_points"})
    )
    agg = agg.merge(best[["player", "best_owner", "best_owner_points"]], on="player", how="left")

    if not draft_df.empty and "player" in draft_df.columns:
        draft_counts = draft_df.groupby("player").size().reset_index(name="times_drafted")
        agg = agg.merge(draft_counts, on="player", how="left")
        agg["times_drafted"] = agg["times_drafted"].fillna(0).astype(int)
    else:
        agg["times_drafted"] = 0

    agg["total_started_points"] = agg["total_started_points"].round(2)
    agg["total_roster_points"] = agg["total_roster_points"].round(2)
    agg["best_owner_points"] = agg["best_owner_points"].fillna(0.0).round(2)

    return agg[empty_cols].sort_values("total_started_points", ascending=False).reset_index(drop=True)
