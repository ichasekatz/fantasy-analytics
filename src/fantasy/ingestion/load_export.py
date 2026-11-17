"""Load and normalize the Fantasy Hall of Fame JSON export into DataFrames."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from fantasy.exceptions import DataIngestionError

if TYPE_CHECKING:
    pass

_project_root = Path(__file__).parents[3]
_raw_dir = _project_root / "data" / "raw"
_leagues_config_path = _project_root / "config" / "leagues.json"


def load_export(path: Path, league_id: str = "default") -> dict[str, pd.DataFrame]:
    """Load and normalize the Fantasy Hall of Fame JSON export.

    Copies the source file to data/raw/ if not already there, then parses
    and normalizes all sections into tidy DataFrames. Every returned DataFrame
    includes a league_id column so multi-league concatenations stay distinct.

    Args:
        path (Path): Absolute path to the JSON export file.
        league_id (str): Stable identifier for this league (e.g. "bigwells-leaguern").

    Returns:
        Dict with keys: 'matchups', 'owners', 'seasons', 'draft_picks',
        'rosters', 'transactions', 'team_period_scores'.

    Raises:
        DataIngestionError: If the file cannot be read or is missing required keys.
    """
    _raw_dir.mkdir(parents=True, exist_ok=True)
    dest = _raw_dir / path.name
    if not dest.exists():
        shutil.copy2(path, dest)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataIngestionError(f"Cannot read export at {path}: {exc}") from exc

    required_keys = {"matchups", "owners", "seasons", "draftPicks", "rosters", "transactions"}
    missing = required_keys - raw.keys()
    if missing:
        raise DataIngestionError(f"Export missing required keys: {missing}")

    frames = {
        "matchups": _normalize_matchups(raw["matchups"]),
        "owners": _normalize_owners(raw["owners"]),
        "seasons": _normalize_seasons(raw["seasons"]),
        "draft_picks": _normalize_draft_picks(raw["draftPicks"]),
        "rosters": _normalize_rosters(raw["rosters"]),
        "transactions": _normalize_transactions(raw["transactions"]),
        "team_period_scores": _normalize_team_period_scores(raw.get("teamPeriodScores", [])),
    }
    for df in frames.values():
        df.insert(0, "league_id", league_id)
    return frames


def load_all_leagues(
    leagues_config_path: Path = _leagues_config_path,
    include_non_primary: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load and concatenate all registered leagues into unified DataFrames.

    Reads config/leagues.json, calls load_export for each registered league,
    applies any season_filter, and concatenates results table by table.

    League config fields:
        primary (bool, default true): When false, the league is a filtered view
            of another entry's data (e.g. "The Big Leagues" is 2022-2023 seasons
            of Bigwell's). Non-primary leagues are still stored in the DB under
            their own league_id so they can be browsed independently, but their
            matchups are NOT included in "All Leagues" aggregations — the same
            data already exists in the primary entry. Set include_non_primary=False
            to load only primary leagues (used for cross-league totals).
        season_filter (list[int] | null): When set, only load seasons in this list.

    Args:
        leagues_config_path (Path): Path to the leagues registry JSON.
        include_non_primary (bool): If False, skip leagues with primary=false.

    Returns:
        Dict with same keys as load_export, with rows from all loaded leagues.

    Raises:
        DataIngestionError: If the config cannot be read or any export fails.
    """
    try:
        config = json.loads(leagues_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataIngestionError(f"Cannot read leagues config at {leagues_config_path}: {exc}") from exc

    all_frames: list[dict[str, pd.DataFrame]] = []
    for entry in config.get("leagues", []):
        is_primary = entry.get("primary", True)
        if not include_non_primary and not is_primary:
            continue

        raw_path = entry.get("export_path", "")
        path = _project_root / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
        league_id = entry["league_id"]
        season_filter: list[int] | None = entry.get("season_filter")

        frames = load_export(path, league_id=league_id)

        # Apply season filter if specified (sub-league view)
        if season_filter:
            season_set = set(int(s) for s in season_filter)
            for key in ("matchups", "rosters", "draft_picks", "transactions", "team_period_scores"):
                if key in frames and "season" in frames[key].columns:
                    frames[key] = frames[key][frames[key]["season"].isin(season_set)].copy()
            if "seasons" in frames:
                frames["seasons"] = frames["seasons"][frames["seasons"]["season"].isin(season_set)].copy()

        all_frames.append(frames)

    if not all_frames:
        raise DataIngestionError("No leagues registered in config/leagues.json")

    table_keys = list(all_frames[0].keys())
    return {
        key: pd.concat([f[key] for f in all_frames], ignore_index=True)
        for key in table_keys
    }


def _normalize_matchups(raw: list[dict]) -> pd.DataFrame:
    """Normalize matchup records into a tidy DataFrame.

    Scores are extracted from teamA.points / teamB.points, which are populated
    for all seasons (ESPN and Sleeper). roundPointsA/B are ESPN-only multi-week
    playoff aggregates and are intentionally ignored here.

    Args:
        raw (list[dict]): Raw matchup list from the JSON export.

    Returns:
        DataFrame with columns: season, week, team_a_id, team_a_name,
        team_a_owner, team_b_id, team_b_name, team_b_owner, points_a,
        points_b, winner_team_id, is_playoff, is_consolation, is_championship.
    """
    rows = []
    for m in raw:
        team_a = m.get("teamA") or {}
        team_b = m.get("teamB") or {}
        rows.append(
            {
                "season": int(m["season"]),
                "week": int(m["week"]) if m.get("week") is not None else None,
                "team_a_id": team_a.get("teamId"),
                "team_a_name": team_a.get("team"),
                "team_a_owner": team_a.get("owner"),
                "team_b_id": team_b.get("teamId"),
                "team_b_name": team_b.get("team"),
                "team_b_owner": team_b.get("owner"),
                "points_a": team_a.get("points"),
                "points_b": team_b.get("points"),
                "winner_team_id": m.get("winnerTeamId"),
                "is_playoff": bool(m.get("playoffs", False)),
                "is_consolation": bool(m.get("consolation", False)),
                "is_championship": bool(m.get("championship", False)),
            }
        )
    df = pd.DataFrame(rows)
    df["points_a"] = pd.to_numeric(df["points_a"], errors="coerce")
    df["points_b"] = pd.to_numeric(df["points_b"], errors="coerce")
    df["week"] = pd.to_numeric(df["week"], errors="coerce").astype("Int64")
    return df


def _normalize_owners(raw: list[dict]) -> pd.DataFrame:
    """Normalize owner records.

    Args:
        raw (list[dict]): Raw owners list from the JSON export.

    Returns:
        DataFrame with columns: owner_id, name, hidden.
    """
    rows = [{"owner_id": o["id"], "name": o["name"], "hidden": bool(o.get("hidden", False))} for o in raw]
    return pd.DataFrame(rows)


def _normalize_seasons(raw: list[dict]) -> pd.DataFrame:
    """Normalize season metadata.

    Args:
        raw (list[dict]): Raw seasons list from the JSON export.

    Returns:
        DataFrame with columns: season, name, provider, num_teams.
    """
    rows = [
        {
            "season": int(s["season"]),
            "name": s.get("name"),
            "provider": s.get("provider"),
            "num_teams": int(s.get("numTeams", 0)),
        }
        for s in raw
    ]
    return pd.DataFrame(rows).sort_values("season").reset_index(drop=True)


def _normalize_draft_picks(raw: list[dict]) -> pd.DataFrame:
    """Normalize draft pick records.

    Args:
        raw (list[dict]): Raw draftPicks list from the JSON export.

    Returns:
        DataFrame with columns: season, round, overall, team_id, team_name,
        owner_id, owner_name, player, position, keeper, cost.
    """
    rows = []
    for p in raw:
        # owner is a plain string (display name) in this export format
        owner_val = p.get("owner")
        owner_name = owner_val if isinstance(owner_val, str) else (owner_val or {}).get("name")
        rows.append(
            {
                "season": int(p["season"]),
                "round": int(p["round"]),
                "overall": int(p["overall"]),
                "team_id": p.get("teamId"),
                "team_name": p.get("team"),
                "owner_name": owner_name,
                "player": p.get("player"),
                "position": p.get("position"),
                "keeper": bool(p.get("keeper", False)),
                "cost": p.get("cost"),
            }
        )
    return pd.DataFrame(rows)


def _normalize_rosters(raw: list[dict]) -> pd.DataFrame:
    """Normalize weekly roster records.

    Args:
        raw (list[dict]): Raw rosters list from the JSON export.

    Returns:
        DataFrame with columns: season, week, team_id, team_name, owner_name,
        player, position, selected_position, starter, points, projected.
    """
    rows = []
    for r in raw:
        owner_val = r.get("owner")
        owner_name = owner_val if isinstance(owner_val, str) else (owner_val or {}).get("name")
        rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "team_id": r.get("teamId"),
                "team_name": r.get("team"),
                "owner_name": owner_name,
                "player": r.get("player"),
                "position": r.get("position"),
                "selected_position": r.get("selectedPosition"),
                "starter": bool(r.get("starter", False)),
                "points": r.get("points"),
                "projected": r.get("projected"),
            }
        )
    df = pd.DataFrame(rows)
    df["points"] = pd.to_numeric(df["points"], errors="coerce")
    df["projected"] = pd.to_numeric(df["projected"], errors="coerce")
    return df


def _normalize_transactions(raw: list[dict]) -> pd.DataFrame:
    """Normalize transaction records (adds, drops, trades, waiver claims).

    Args:
        raw (list[dict]): Raw transactions list from the JSON export.

    Returns:
        DataFrame with columns: season, week, type, status, timestamp,
        parties, players.
    """
    rows = []
    for t in raw:
        rows.append(
            {
                "season": int(t["season"]),
                "week": t.get("week"),
                "type": t.get("type"),
                "status": t.get("status"),
                "timestamp": t.get("timestamp"),
                "parties": json.dumps(t.get("parties", [])),
                "players": json.dumps(t.get("players", [])),
            }
        )
    return pd.DataFrame(rows)


def _normalize_team_period_scores(raw: list[dict]) -> pd.DataFrame:
    """Normalize team period (weekly) score records.

    Args:
        raw (list[dict]): Raw teamPeriodScores list from the JSON export.

    Returns:
        DataFrame with columns: league_season_id, team_id, period, points, status.
    """
    rows = [
        {
            "league_season_id": r.get("leagueSeasonId"),
            "team_id": r.get("teamId"),
            "period": r.get("period"),
            "points": r.get("points"),
            "status": r.get("status"),
        }
        for r in raw
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["points"] = pd.to_numeric(df["points"], errors="coerce")
    return df
