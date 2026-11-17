"""Cross-league analytics using canonical manager identities."""

from __future__ import annotations

import pandas as pd

from fantasy.analytics.standings import _filter_league, _regular_season
from fantasy.identity.enrichment import enrich_matchups


def cross_league_standings(matchups_df: pd.DataFrame, registry: dict) -> pd.DataFrame:
    """Compute career W/L/PF/PA per canonical manager across all leagues.

    Uses canonical display names when available, raw owner names otherwise.
    Only includes regular-season matchups.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame with league_id column.
        registry (dict): Loaded canonical manager registry.

    Returns:
        DataFrame with columns: manager, wins, losses, ties, win_pct,
        points_for, points_against, seasons_played, avg_pf, leagues,
        sorted by win_pct desc.
    """
    enriched = enrich_matchups(matchups_df, registry)
    # Filter to regular season only across all leagues
    reg = enriched[~enriched["is_playoff"] & ~enriched["is_consolation"] & ~enriched["is_championship"]].copy()

    if reg.empty:
        return pd.DataFrame()

    records: dict[str, dict] = {}

    def _ensure(display: str) -> None:
        if display not in records:
            records[display] = {
                "wins": 0, "losses": 0, "ties": 0,
                "points_for": 0.0, "points_against": 0.0,
                "season_set": set(), "league_set": set(),
            }

    for _, row in reg.iterrows():
        da = row["canonical_display_a"]
        db = row["canonical_display_b"]
        pa, pb = row["points_a"] or 0.0, row["points_b"] or 0.0
        league = row.get("league_id", "")
        season = row.get("season", 0)

        _ensure(da)
        _ensure(db)
        records[da]["points_for"] += pa
        records[da]["points_against"] += pb
        records[da]["season_set"].add((league, season))
        records[da]["league_set"].add(league)
        records[db]["points_for"] += pb
        records[db]["points_against"] += pa
        records[db]["season_set"].add((league, season))
        records[db]["league_set"].add(league)

        if row["winner_team_id"] == row["team_a_id"]:
            records[da]["wins"] += 1
            records[db]["losses"] += 1
        elif row["winner_team_id"] == row["team_b_id"]:
            records[db]["wins"] += 1
            records[da]["losses"] += 1
        else:
            records[da]["ties"] += 1
            records[db]["ties"] += 1

    rows = []
    for manager, r in records.items():
        games = r["wins"] + r["losses"] + r["ties"]
        win_pct = (r["wins"] + 0.5 * r["ties"]) / games if games else float("nan")
        rows.append({
            "manager": manager,
            "wins": r["wins"],
            "losses": r["losses"],
            "ties": r["ties"],
            "win_pct": round(win_pct, 3),
            "points_for": round(r["points_for"], 2),
            "points_against": round(r["points_against"], 2),
            "seasons_played": len(r["season_set"]),
            "avg_pf": round(r["points_for"] / games, 2) if games else float("nan"),
            "leagues": ", ".join(sorted(r["league_set"])),
        })

    return (
        pd.DataFrame(rows)
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )


def head_to_head_all_leagues(
    matchups_df: pd.DataFrame,
    registry: dict,
    canonical_id_a: str,
    canonical_id_b: str,
) -> pd.DataFrame:
    """Return all matchups between two canonical managers across all leagues.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame with league_id column.
        registry (dict): Loaded canonical manager registry.
        canonical_id_a (str): Canonical ID of first manager.
        canonical_id_b (str): Canonical ID of second manager.

    Returns:
        DataFrame of all head-to-head matchups, with columns: season, week,
        league_id, display_a, pts_a, pts_b, display_b, winner_display,
        is_playoff, is_championship. Sorted by season, week.
    """
    enriched = enrich_matchups(matchups_df, registry)

    mask = (
        ((enriched["canonical_id_a"] == canonical_id_a) & (enriched["canonical_id_b"] == canonical_id_b))
        | ((enriched["canonical_id_a"] == canonical_id_b) & (enriched["canonical_id_b"] == canonical_id_a))
    )
    h2h = enriched[mask].copy()

    if h2h.empty:
        return pd.DataFrame()

    rows = []
    for _, row in h2h.iterrows():
        is_a_first = row["canonical_id_a"] == canonical_id_a
        pts_a = row["points_a"] if is_a_first else row["points_b"]
        pts_b = row["points_b"] if is_a_first else row["points_a"]
        display_a = row["canonical_display_a"] if is_a_first else row["canonical_display_b"]
        display_b = row["canonical_display_b"] if is_a_first else row["canonical_display_a"]

        if row["winner_team_id"] == row["team_a_id"]:
            winner_display = row["canonical_display_a"]
        elif row["winner_team_id"] == row["team_b_id"]:
            winner_display = row["canonical_display_b"]
        else:
            winner_display = "Tie"

        rows.append({
            "season": row["season"],
            "week": row.get("week"),
            "league_id": row.get("league_id", ""),
            "display_a": display_a,
            "pts_a": pts_a,
            "pts_b": pts_b,
            "display_b": display_b,
            "winner": winner_display,
            "is_playoff": row["is_playoff"],
            "is_championship": row["is_championship"],
        })

    return pd.DataFrame(rows).sort_values(["season", "week"]).reset_index(drop=True)
