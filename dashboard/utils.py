"""Shared dashboard utilities."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

# Columns in any DataFrame that contain owner names and should be resolved
_OWNER_COLS = {"owner_name", "team_a_owner", "team_b_owner", "owner", "owner_drop", "owner_add", "champion", "runner_up"}

_project_root = Path(__file__).parents[1]
_leagues_config_path = _project_root / "config" / "leagues.json"


@lru_cache(maxsize=1)
def _load_leagues_config_cached(mtime: float) -> dict:
    """Load leagues.json, keyed by mtime so edits invalidate the cache."""
    try:
        return json.loads(_leagues_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"leagues": []}


def _leagues_config() -> dict:
    mtime = _leagues_config_path.stat().st_mtime if _leagues_config_path.exists() else 0.0
    return _load_leagues_config_cached(mtime)


def _season_filter_for(league_id: str) -> list[int] | None:
    """Return the season_filter list for a league, or None if all seasons included."""
    for entry in _leagues_config().get("leagues", []):
        if entry["league_id"] == league_id:
            return entry.get("season_filter")  # None = all seasons
    return None


def _primary_league_ids() -> set[str]:
    """Return league_ids where primary is True (or unset, which defaults to True)."""
    return {
        e["league_id"]
        for e in _leagues_config().get("leagues", [])
        if e.get("primary", True)
    }


def build_name_map(conn) -> dict[str, str]:
    """Build raw_name → canonical display_name map from the identity registry.

    Also maps team names (e.g. "Ford F150") → canonical owner name so that
    trade / waiver data extracted from parties JSON resolves correctly.

    Returns empty dict if identity tables are missing or empty.
    """
    mapping: dict[str, str] = {}
    try:
        rows = conn.execute("""
            SELECT ma.raw_name, cm.display_name
            FROM manager_aliases ma
            JOIN canonical_managers cm ON ma.canonical_id = cm.canonical_id
        """).fetchall()
        mapping.update({raw: display for raw, display in rows if raw != display})
    except Exception:
        pass

    # Also map team names → canonical owner names from rosters (column is team_name not team)
    try:
        team_rows = conn.execute("""
            SELECT DISTINCT team_name, owner_name
            FROM rosters
            WHERE team_name IS NOT NULL AND team_name != '' AND owner_name IS NOT NULL AND owner_name != ''
        """).fetchall()
        for tn, on in team_rows:
            if tn and on and tn != on:
                # Resolve through aliases so we get canonical display_name, not raw username
                canonical = mapping.get(on, on)
                mapping[tn] = canonical
    except Exception:
        pass

    return mapping


def resolve_owner_names(df: pd.DataFrame) -> pd.DataFrame:
    """Replace raw owner name strings with canonical display names.

    Uses the name map cached in st.session_state['_name_map'].
    No-op if the map is empty or the column doesn't exist.
    """
    name_map: dict[str, str] = st.session_state.get("_name_map", {})
    if not name_map:
        return df
    df = df.copy()
    for col in _OWNER_COLS:
        if col in df.columns:
            df[col] = df[col].map(lambda x: name_map.get(x, x) if isinstance(x, str) else x)
    return df


def apply_league_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame by selected league, season_filter, and excluded players.

    Applies layers in order:
    1. If a specific league is selected: filter to that league_id + its season_filter.
    2. If "All Leagues" (no selection): exclude non-primary leagues to prevent
       double-counting sub-views (e.g. The Big Leagues overlapping with Bigwells).
    3. Player exclusions from session state (always applied).

    Args:
        df: Any DataFrame that may have league_id / season / player columns.

    Returns:
        Filtered copy, or original if nothing applies.
    """
    lid: str | None = st.session_state.get("selected_league_id")

    if lid and "league_id" in df.columns:
        # Specific league selected
        df = df[df["league_id"] == lid].copy()

        # Apply that league's season_filter
        if "season" in df.columns:
            season_filter = _season_filter_for(lid)
            if season_filter is not None:
                df = df[df["season"].isin(season_filter)]

    elif "league_id" in df.columns:
        # All Leagues: drop non-primary sub-views to avoid double-counting
        primary_ids = _primary_league_ids()
        if primary_ids:
            df = df[df["league_id"].isin(primary_ids)].copy()

        # Apply format filter (redraft_only / dynasty_only / all)
        fmt: str = st.session_state.get("league_format", "redraft_only")
        if fmt == "redraft_only":
            df = df[~df["league_id"].apply(is_dynasty_league)].copy()
        elif fmt == "dynasty_only":
            df = df[df["league_id"].apply(is_dynasty_league)].copy()

    # Global season range filter
    season_range = st.session_state.get("season_range")
    if season_range is not None and "season" in df.columns:
        yr_min, yr_max = season_range
        df = df[(df["season"] >= yr_min) & (df["season"] <= yr_max)].copy()

    # IDP exclusion
    if st.session_state.get("exclude_defensive", False):
        # Rosters/player tables: strip defensive rows
        if "position" in df.columns and "points_a" not in df.columns:
            df = df[~df["position"].apply(
                lambda p: is_defensive_position(str(p)) if pd.notna(p) else False
            )].copy()

        # Matchups tables: rebuild points_a/points_b/winner using offensive-only rosters
        if "points_a" in df.columns and "points_b" in df.columns and "winner_team_id" in df.columns:
            conn = st.session_state.get("_conn")
            if conn is not None:
                try:
                    lid = st.session_state.get("selected_league_id")
                    # Load all starters; filter by league in pandas to avoid SQL injection
                    rdf = conn.execute(
                        "SELECT season, week, owner_name, league_id, position, points, starter FROM rosters"
                    ).df()
                    if lid and "league_id" in rdf.columns:
                        rdf = rdf[rdf["league_id"] == lid]
                    # Filter to starters only (handle both BOOLEAN and INTEGER column types)
                    rdf = rdf[rdf["starter"].fillna(False).astype(bool)]
                    # Strip defensive positions
                    rdf = rdf[~rdf["position"].apply(
                        lambda p: is_defensive_position(str(p)) if pd.notna(p) else False
                    )]
                    rdf["points"] = pd.to_numeric(rdf["points"], errors="coerce").fillna(0)
                    rdf["week"] = pd.to_numeric(rdf["week"], errors="coerce")
                    rdf["season"] = pd.to_numeric(rdf["season"], errors="coerce")
                    rdf = rdf.dropna(subset=["week", "season"])
                    rdf["season"] = rdf["season"].astype(int)
                    rdf["week"] = rdf["week"].astype(int)
                    weekly = rdf.groupby(["season", "week", "owner_name"])["points"].sum().reset_index()
                    score_map = {
                        (int(r["season"]), int(r["week"]), r["owner_name"]): r["points"]
                        for _, r in weekly.iterrows()
                    }
                    if score_map:
                        df = df.copy()
                        df["_wk"] = pd.to_numeric(df["week"], errors="coerce").fillna(0).astype(int)
                        df["_sea"] = pd.to_numeric(df["season"], errors="coerce").fillna(0).astype(int)
                        df["points_a"] = df.apply(
                            lambda r: score_map.get((r["_sea"], r["_wk"], r["team_a_owner"]), r["points_a"]), axis=1
                        )
                        df["points_b"] = df.apply(
                            lambda r: score_map.get((r["_sea"], r["_wk"], r["team_b_owner"]), r["points_b"]), axis=1
                        )
                        df["winner_team_id"] = df.apply(
                            lambda r: r["team_a_id"]
                            if pd.notna(r["points_a"]) and pd.notna(r["points_b"]) and r["points_a"] >= r["points_b"]
                            else r["team_b_id"],
                            axis=1,
                        )
                        df = df.drop(columns=["_wk", "_sea"])
                except Exception:
                    pass  # fall through, return original scores

    # Always strip HC (Head Coach) rows — not a real fantasy scoring position
    if "position" in df.columns:
        df = df[~df["position"].apply(
            lambda p: str(p).strip().upper() == "HC" if pd.notna(p) else False
        )].copy()

    # Player exclusions (session-only, always applied)
    excluded: list[str] = st.session_state.get("excluded_players", [])
    if excluded and "player" in df.columns:
        df = df[~df["player"].isin(excluded)]

    return resolve_owner_names(df)


# ---------------------------------------------------------------------------
# Dynasty league helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# IDP / defensive position helpers
# ---------------------------------------------------------------------------

# Individual IDP defensive positions only — K, DST/DEF/D_ST are intentionally excluded.
_DEFENSIVE_POSITION_TOKENS = {"CB", "DB", "DE", "DL", "DT", "HC", "LB", "S", "SS", "FS", "IDP_FLEX"}
# Non-IDP positions that must never be treated as defensive regardless of naming
_OFFENSIVE_POSITION_TOKENS = {"K", "DST", "DEF", "D_ST", "D/ST", "P", "QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "OP"}


def is_defensive_position(pos: str) -> bool:
    """Return True if ALL tokens are IDP-defensive and none are explicitly non-defensive (K, DST, etc.)."""
    if not pos or not isinstance(pos, str):
        return False
    tokens = {t.strip() for t in pos.split(",")}
    if not tokens:
        return False
    if tokens & _OFFENSIVE_POSITION_TOKENS:
        return False
    return tokens.issubset(_DEFENSIVE_POSITION_TOKENS)


# Positions excluded by LOCAL IDP toggles (broader than global — also strips K and DST/DEF)
_LOCAL_IDP_EXCLUDE_TOKENS = {"K", "DST", "DEF", "D_ST", "D/ST"}


def is_non_skill_position(pos: str) -> bool:
    """Return True for IDP defensive positions AND kickers/DST (for local IDP toggles)."""
    if not pos or not isinstance(pos, str):
        return False
    tokens = {t.strip() for t in pos.split(",")}
    return bool(tokens & _LOCAL_IDP_EXCLUDE_TOKENS) or is_defensive_position(pos)


def season_has_idp(roster_df: pd.DataFrame, season: int) -> bool:
    """Return True if any starter in season has a defensive position."""
    s = roster_df[(roster_df["season"] == season) & (roster_df["starter"] == True)]
    return any(is_defensive_position(str(p)) for p in s["position"].dropna())


def filter_offensive_rosters(roster_df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows where position is purely defensive."""
    mask = ~roster_df["position"].apply(lambda p: is_defensive_position(str(p)) if pd.notna(p) else False)
    return roster_df[mask].copy()


def rebuild_matchups_offensive(matchups_df: pd.DataFrame, rosters_df: pd.DataFrame) -> pd.DataFrame:
    """Recompute points_a/points_b/winner_team_id from offensive-only starters.

    Use when exclude_defensive is True to strip IDP scores from standings.
    Returns matchups_df unchanged if rosters_df is empty or no IDP flag set.
    """
    if rosters_df.empty or not st.session_state.get("exclude_defensive", False):
        return matchups_df

    # Only recalculate seasons that actually had IDP starters — leave other seasons untouched
    idp_seasons = {
        int(s) for s in rosters_df["season"].dropna().unique()
        if season_has_idp(rosters_df, int(s))
    }
    if not idp_seasons:
        return matchups_df

    starters = rosters_df[
        rosters_df["starter"].fillna(False) & rosters_df["season"].isin(idp_seasons)
    ].copy()
    starters = filter_offensive_rosters(starters)
    starters["points"] = pd.to_numeric(starters["points"], errors="coerce").fillna(0)
    starters["week"] = pd.to_numeric(starters["week"], errors="coerce")
    starters = starters.dropna(subset=["week"])
    starters["week"] = starters["week"].astype(int)

    weekly = (
        starters.groupby(["season", "week", "owner_name"])["points"]
        .sum()
        .reset_index()
    )
    score_map = {
        (int(r["season"]), int(r["week"]), r["owner_name"]): r["points"]
        for _, r in weekly.iterrows()
    }

    mdf = matchups_df.copy()
    mdf["_wk"] = pd.to_numeric(mdf["week"], errors="coerce").fillna(0).astype(int)
    mdf["_sea"] = pd.to_numeric(mdf["season"], errors="coerce").fillna(0).astype(int)
    # Only update rows from IDP seasons; non-IDP seasons keep original scores
    mdf["points_a"] = mdf.apply(
        lambda r: score_map.get((r["_sea"], r["_wk"], r["team_a_owner"]), r["points_a"])
        if r["_sea"] in idp_seasons else r["points_a"], axis=1
    )
    mdf["points_b"] = mdf.apply(
        lambda r: score_map.get((r["_sea"], r["_wk"], r["team_b_owner"]), r["points_b"])
        if r["_sea"] in idp_seasons else r["points_b"], axis=1
    )
    mdf["winner_team_id"] = mdf.apply(
        lambda r: r["team_a_id"]
        if pd.notna(r["points_a"]) and pd.notna(r["points_b"]) and r["points_a"] >= r["points_b"]
        else r["team_b_id"],
        axis=1,
    )
    return mdf.drop(columns=["_wk", "_sea"])


_DYNASTY_LEAGUE_KEYWORDS = {"dynasty"}


def is_dynasty_league(league_id: str) -> bool:
    """Return True if league_id contains 'dynasty' (case-insensitive)."""
    return any(kw in league_id.lower() for kw in _DYNASTY_LEAGUE_KEYWORDS)


def filter_redraft(df: pd.DataFrame) -> pd.DataFrame:
    """Remove dynasty league rows (used when no specific league is selected)."""
    if "league_id" not in df.columns:
        return df
    return df[~df["league_id"].apply(is_dynasty_league)].copy()


# ---------------------------------------------------------------------------
# Color-coded dataframe styler
# ---------------------------------------------------------------------------

def style_dataframe(
    df: pd.DataFrame,
    higher_is_better: list[str] | None = None,
    lower_is_better: list[str] | None = None,
    zero_centered: list[str] | None = None,
) -> "pd.io.formats.style.Styler":
    """Apply RdYlGn background gradient to numeric columns.

    higher_is_better: columns where green=high (wins, points, win%)
    lower_is_better: columns where green=low (losses, finish rank)
    zero_centered: columns where 0=yellow, positive=green, negative=red
                   regardless of the range of values in the column
    """
    styler = df.style
    for col in (higher_is_better or []):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            styler = styler.background_gradient(cmap="RdYlGn", subset=[col], axis=0)
    for col in (lower_is_better or []):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            styler = styler.background_gradient(cmap="RdYlGn_r", subset=[col], axis=0)
    for col in (zero_centered or []):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            col_vals = df[col].dropna()
            if not col_vals.empty:
                max_abs = max(abs(col_vals.min()), abs(col_vals.max()), 0.01)
                styler = styler.background_gradient(
                    cmap="RdYlGn", subset=[col], axis=0,
                    vmin=-max_abs, vmax=max_abs,
                )
    return styler
