"""Enrich DataFrames with canonical manager identity columns."""

from __future__ import annotations

import pandas as pd

from fantasy.identity.registry import build_name_lookup


def enrich_matchups(matchups_df: pd.DataFrame, registry: dict) -> pd.DataFrame:
    """Add canonical manager columns to a matchups DataFrame.

    Resolves team_a_owner and team_b_owner strings against the registry using
    (league_id, raw_name) lookups. Falls back to the raw owner name when no
    canonical mapping exists.

    Args:
        matchups_df (pd.DataFrame): Matchups DataFrame with league_id,
            team_a_owner, team_b_owner columns.
        registry (dict): Loaded canonical manager registry.

    Returns:
        Copy of matchups_df with added columns: canonical_id_a,
        canonical_display_a, canonical_id_b, canonical_display_b.
    """
    df = matchups_df.copy()
    lookup = build_name_lookup(registry)

    league_col = "league_id" if "league_id" in df.columns else None

    def _resolve(league_id: str, name: str | None) -> tuple[str, str]:
        if not name:
            return ("", "Unknown")
        result = lookup.get((league_id, name))
        if result:
            return result
        return ("", name)

    if league_col:
        resolved_a = df.apply(lambda r: _resolve(r[league_col], r["team_a_owner"]), axis=1)
        resolved_b = df.apply(lambda r: _resolve(r[league_col], r["team_b_owner"]), axis=1)
    else:
        resolved_a = df.apply(lambda r: _resolve("", r["team_a_owner"]), axis=1)
        resolved_b = df.apply(lambda r: _resolve("", r["team_b_owner"]), axis=1)

    df["canonical_id_a"] = [r[0] for r in resolved_a]
    df["canonical_display_a"] = [r[1] for r in resolved_a]
    df["canonical_id_b"] = [r[0] for r in resolved_b]
    df["canonical_display_b"] = [r[1] for r in resolved_b]
    return df


def enrich_owners(owners_df: pd.DataFrame, registry: dict) -> pd.DataFrame:
    """Add canonical manager columns to an owners DataFrame.

    Resolves owner_id against the registry using (league_id, raw_owner_id)
    lookups. Falls back to raw owner name when no canonical mapping exists.

    Args:
        owners_df (pd.DataFrame): Owners DataFrame with league_id,
            owner_id, name columns.
        registry (dict): Loaded canonical manager registry.

    Returns:
        Copy of owners_df with added columns: canonical_id, canonical_display.
    """
    df = owners_df.copy()

    # Build ID-based lookup: (league_id, raw_owner_id) -> (canonical_id, display_name)
    id_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for manager in registry.get("canonical_managers", []):
        cid = manager["canonical_id"]
        dname = manager["display_name"]
        for alias in manager.get("aliases", []):
            key = (alias.get("league_id", ""), alias.get("raw_owner_id", ""))
            id_lookup[key] = (cid, dname)

    league_col = "league_id" if "league_id" in df.columns else None

    def _resolve(league_id: str, owner_id: str, name: str) -> tuple[str, str]:
        result = id_lookup.get((league_id, owner_id))
        if result:
            return result
        return ("", name)

    if league_col:
        resolved = df.apply(lambda r: _resolve(r[league_col], r["owner_id"], r["name"]), axis=1)
    else:
        resolved = df.apply(lambda r: _resolve("", r["owner_id"], r["name"]), axis=1)

    df["canonical_id"] = [r[0] for r in resolved]
    df["canonical_display"] = [r[1] for r in resolved]
    return df
