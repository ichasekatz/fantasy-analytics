"""DuckDB connection management and table initialization."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from fantasy.ingestion.load_export import load_all_leagues, load_export

_db_dir = Path(__file__).parents[4] / "data" / "database"
_default_db_path = _db_dir / "fantasy.duckdb"

_data_tables = ["matchups", "owners", "seasons", "draft_picks", "rosters", "transactions", "team_period_scores"]
_identity_tables = ["canonical_managers", "manager_aliases"]


def get_connection(db_path: Path = _default_db_path) -> duckdb.DuckDBPyConnection:
    """Open (or create) a persistent DuckDB connection.

    Args:
        db_path (Path): Path to the DuckDB database file.

    Returns:
        An open DuckDB connection.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def initialize_database(conn: duckdb.DuckDBPyConnection, frames: dict[str, pd.DataFrame]) -> None:
    """Create data tables from normalized DataFrames, dropping existing ones.

    All tables include a league_id column. Identity tables (canonical_managers,
    manager_aliases) are created if they do not already exist and are never
    dropped here — use update_identity_tables to sync them.

    Args:
        conn (duckdb.DuckDBPyConnection): Open DuckDB connection.
        frames (dict[str, pd.DataFrame]): Mapping of table name → DataFrame.
    """
    for name in _data_tables:
        if name not in frames:
            continue
        df = frames[name]  # noqa: F841
        conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.execute(f"CREATE TABLE {name} AS SELECT * FROM df")

    _ensure_identity_tables(conn)


def _ensure_identity_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create identity tables if they do not exist.

    Args:
        conn (duckdb.DuckDBPyConnection): Open DuckDB connection.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canonical_managers (
            canonical_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_aliases (
            alias_id TEXT PRIMARY KEY,
            canonical_id TEXT,
            league_id TEXT NOT NULL,
            raw_owner_id TEXT NOT NULL,
            raw_name TEXT NOT NULL
        )
    """)


def update_identity_tables(conn: duckdb.DuckDBPyConnection, registry: dict) -> None:
    """Sync the JSON identity registry into the DuckDB identity tables.

    Truncates and rebuilds canonical_managers and manager_aliases from the
    registry dict. Raw league data is never modified.

    Args:
        conn (duckdb.DuckDBPyConnection): Open DuckDB connection.
        registry (dict): Loaded registry dict with key 'canonical_managers'.
    """
    _ensure_identity_tables(conn)
    conn.execute("DELETE FROM manager_aliases")
    conn.execute("DELETE FROM canonical_managers")

    manager_rows = []
    alias_rows = []
    for manager in registry.get("canonical_managers", []):
        manager_rows.append({
            "canonical_id": manager["canonical_id"],
            "display_name": manager["display_name"],
            "notes": manager.get("notes"),
        })
        for alias in manager.get("aliases", []):
            alias_id = f"{alias.get('league_id', '')}::{alias.get('raw_owner_id', '')}"
            alias_rows.append({
                "alias_id": alias_id,
                "canonical_id": manager["canonical_id"],
                "league_id": alias.get("league_id", ""),
                "raw_owner_id": alias.get("raw_owner_id", ""),
                "raw_name": alias.get("raw_name", ""),
            })

    if manager_rows:
        df_m = pd.DataFrame(manager_rows)  # noqa: F841
        conn.execute("INSERT INTO canonical_managers SELECT * FROM df_m")
    if alias_rows:
        df_a = pd.DataFrame(alias_rows)  # noqa: F841
        conn.execute("INSERT INTO manager_aliases SELECT * FROM df_a")


def reload_all_leagues(db_path: Path = _default_db_path) -> duckdb.DuckDBPyConnection:
    """Reload the database from all registered leagues, replacing data tables.

    Reads config/leagues.json, ingests every league export, and rebuilds all
    data tables. Identity tables are preserved and not modified.

    Args:
        db_path (Path): Path to the DuckDB database file.

    Returns:
        An open DuckDB connection with refreshed data.
    """
    frames = load_all_leagues()
    conn = get_connection(db_path)
    initialize_database(conn, frames)
    return conn


def update_from_export(export_path: Path, db_path: Path = _default_db_path) -> duckdb.DuckDBPyConnection:
    """Reload the database from a single export file, replacing all data tables.

    Args:
        export_path (Path): Path to the new JSON export file.
        db_path (Path): Path to the DuckDB database file.

    Returns:
        An open DuckDB connection with refreshed data.
    """
    frames = load_export(export_path)
    conn = get_connection(db_path)
    initialize_database(conn, frames)
    return conn


def load_from_export(export_path: Path, db_path: Path = _default_db_path) -> duckdb.DuckDBPyConnection:
    """Load the database, initializing from all registered leagues if tables are missing.

    On first run (or if tables are missing), builds all tables from the
    registry. On subsequent runs with an existing DB, returns the connection.
    If the existing matchups table lacks a league_id column, triggers a reload.

    Args:
        export_path (Path): Path to the JSON export file (used only as fallback).
        db_path (Path): Path to the DuckDB database file.

    Returns:
        An open DuckDB connection.
    """
    conn = get_connection(db_path)
    existing = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}

    needs_reload = not existing.issuperset(set(_data_tables))
    if not needs_reload and "matchups" in existing:
        # Check league_id column exists (migration from old schema)
        cols = {r[0] for r in conn.execute("DESCRIBE matchups").fetchall()}
        if "league_id" not in cols:
            needs_reload = True

    if needs_reload:
        try:
            frames = load_all_leagues()
        except Exception:
            frames = load_export(export_path)
        initialize_database(conn, frames)
    else:
        _ensure_identity_tables(conn)

    return conn
