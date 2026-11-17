"""Shared dashboard utilities."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

# Columns in any DataFrame that contain owner names and should be resolved
_OWNER_COLS = {"owner_name", "team_a_owner", "team_b_owner", "owner", "champion", "runner_up"}

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

    Returns empty dict if identity tables are missing or empty.
    """
    try:
        rows = conn.execute("""
            SELECT ma.raw_name, cm.display_name
            FROM manager_aliases ma
            JOIN canonical_managers cm ON ma.canonical_id = cm.canonical_id
        """).fetchall()
        return {raw: display for raw, display in rows if raw != display}
    except Exception:
        return {}


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

# Positions that are exclusively defensive (IDP or team defense).
# In 2019 (ESPN), these appear as starters. Later Sleeper seasons have none.
_DEFENSIVE_POSITION_TOKENS = {"CB", "DB", "DE", "DL", "DT", "LB", "S", "SS", "HC", "DEF", "IDP_FLEX"}


def is_defensive_position(pos: str) -> bool:
    """Return True if ALL tokens in a position string are defensive."""
    if not pos or not isinstance(pos, str):
        return False
    tokens = {t.strip() for t in pos.split(",")}
    return bool(tokens) and tokens.issubset(_DEFENSIVE_POSITION_TOKENS)


def season_has_idp(roster_df: pd.DataFrame, season: int) -> bool:
    """Return True if any starter in season has a defensive position."""
    s = roster_df[(roster_df["season"] == season) & (roster_df["starter"] == True)]
    return any(is_defensive_position(str(p)) for p in s["position"].dropna())


def filter_offensive_rosters(roster_df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows where position is purely defensive."""
    mask = ~roster_df["position"].apply(lambda p: is_defensive_position(str(p)) if pd.notna(p) else False)
    return roster_df[mask].copy()


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
) -> "pd.io.formats.style.Styler":
    """Apply RdYlGn background gradient to numeric columns.

    higher_is_better: columns where green=high (wins, points, win%)
    lower_is_better: columns where green=low (losses, finish rank)
    """
    styler = df.style
    for col in (higher_is_better or []):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            styler = styler.background_gradient(cmap="RdYlGn", subset=[col], axis=0)
    for col in (lower_is_better or []):
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            styler = styler.background_gradient(cmap="RdYlGn_r", subset=[col], axis=0)
    return styler
