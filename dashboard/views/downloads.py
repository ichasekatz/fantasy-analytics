"""Downloads page: full dataset per league and external analytics data."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

_project_root = Path(__file__).parents[2]
_raw_dir = _project_root / "data" / "raw"
_external_dir = _project_root / "data" / "external"
_leagues_config_path = _project_root / "config" / "leagues.json"

_db_tables = ["matchups", "seasons", "owners", "draft_picks", "rosters", "transactions"]


def _safe_read(conn, table: str, league_id: str | None = None) -> pd.DataFrame:
    try:
        if league_id:
            return conn.execute(
                f"SELECT * FROM {table} WHERE league_id = ?", [league_id]  # noqa: S608
            ).df()
        return conn.execute(f"SELECT * FROM {table}").df()  # noqa: S608
    except Exception:
        return pd.DataFrame()


def _build_league_zip(conn, league_id: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in _db_tables:
            df = _safe_read(conn, table, league_id)
            if not df.empty:
                zf.writestr(f"{table}.csv", df.to_csv(index=False))
    buf.seek(0)
    return buf.read()


def render(conn) -> None:
    """Render the Downloads page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("⬇️ Downloads")

    # ── Per-League Full Dataset ──────────────────────────────────────────────
    st.subheader("Full Dataset per League")
    st.caption("Each download is a ZIP of CSVs: matchups, rosters, draft picks, transactions, owners, seasons.")

    try:
        config = json.loads(_leagues_config_path.read_text(encoding="utf-8"))
        leagues = config.get("leagues", [])
    except (OSError, json.JSONDecodeError):
        leagues = []

    if leagues:
        cols = st.columns(min(len(leagues), 3))
        for i, entry in enumerate(leagues):
            lid = entry["league_id"]
            name = entry["name"]
            is_primary = entry.get("primary", True)
            col = cols[i % len(cols)]
            with col:
                label = name if is_primary else f"{name} ↳"
                try:
                    zip_bytes = _build_league_zip(conn, lid)
                    st.download_button(
                        f"⬇️ {label}",
                        zip_bytes,
                        f"{lid}.zip",
                        "application/zip",
                        key=f"dl_league_{lid}",
                    )
                    size_kb = len(zip_bytes) / 1024
                    st.caption(f"{size_kb:.0f} KB")
                except Exception as exc:
                    st.error(f"{name}: {exc}")
    else:
        st.info("No leagues registered in config/leagues.json.")

    st.divider()

    # ── External Analytics Data ──────────────────────────────────────────────
    st.subheader("External Analytics Data")
    st.caption("NFL player stats and draft value data fetched from nfl_data_py. Use these for ADP and performance benchmarking outside your leagues.")

    ext_files = sorted(_external_dir.glob("*.parquet")) if _external_dir.exists() else []
    if not ext_files:
        st.info("No external data cached. Click 'Reload Data' in the sidebar to fetch.")
    else:
        for pf in ext_files:
            c1, c2, c3 = st.columns([3, 1, 2])
            try:
                df = pd.read_parquet(pf)
                label_map = {
                    "nfl_weekly_stats": "NFL Weekly Player Stats",
                    "nfl_seasonal_stats": "NFL Seasonal Player Stats",
                    "historical_adp": "Draft Pick Value / ADP",
                }
                display = label_map.get(pf.stem, pf.stem)
                with c1:
                    st.markdown(f"**{display}**")
                    st.caption(pf.stem)
                with c2:
                    st.caption(f"{len(df):,} rows")
                with c3:
                    st.download_button(
                        f"⬇️ {pf.stem}.csv",
                        df.to_csv(index=False).encode("utf-8"),
                        f"{pf.stem}.csv",
                        "text/csv",
                        key=f"dl_ext_{pf.stem}",
                    )
            except Exception as exc:
                with c1:
                    st.error(f"{pf.name}: {exc}")
