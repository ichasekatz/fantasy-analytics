"""Downloads page: every table as CSV, raw JSON files, and analytics exports."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import career_standings

_project_root = Path(__file__).parents[2]
_raw_dir = _project_root / "data" / "raw"
_identity_dir = _project_root / "data" / "identity"
_external_dir = _project_root / "data" / "external"

_db_tables = ["matchups", "seasons", "owners", "draft_picks", "rosters", "transactions"]


def _safe_read(conn, table: str) -> pd.DataFrame:
    """Read a table from DuckDB, returning empty DataFrame on failure.

    Args:
        conn: DuckDB connection.
        table: Table name to read.

    Returns:
        DataFrame or empty DataFrame if table missing.
    """
    try:
        return conn.execute(f"SELECT * FROM {table}").df()  # noqa: S608
    except Exception:
        return pd.DataFrame()


def render(conn) -> None:
    """Render the Downloads page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("⬇️ Downloads")
    st.caption("Download any table as CSV, or grab the raw source files.")

    # --- Raw Data ---
    st.subheader("Raw Source Files")
    col1, col2, col3 = st.columns(3)

    json_files = list(_raw_dir.glob("*.json")) if _raw_dir.exists() else []
    for i, jf in enumerate(sorted(json_files)):
        col = [col1, col2, col3][i % 3]
        with col:
            try:
                data = jf.read_bytes()
                st.download_button(
                    f"⬇️ {jf.name}",
                    data, jf.name, "application/json",
                    key=f"dl_raw_{jf.stem}",
                )
                st.caption(f"{len(data) / 1024:.1f} KB")
            except OSError:
                st.error(f"Could not read {jf.name}")

    aliases_path = _identity_dir / "manager_aliases.json"
    with col3:
        if aliases_path.exists():
            try:
                data = aliases_path.read_bytes()
                st.download_button(
                    "⬇️ manager_aliases.json",
                    data, "manager_aliases.json", "application/json",
                    key="dl_aliases",
                )
                st.caption(f"{len(data) / 1024:.1f} KB")
            except OSError:
                pass

    st.divider()

    # --- League Tables ---
    st.subheader("League Database Tables")
    for i, table in enumerate(_db_tables):
        df = _safe_read(conn, table)
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            st.markdown(f"**{table}**")
        with c2:
            st.caption(f"{len(df):,} rows")
        with c3:
            if not df.empty:
                st.download_button(
                    f"⬇️ {table}.csv",
                    df.to_csv(index=False).encode("utf-8"),
                    f"{table}.csv", "text/csv",
                    key=f"dl_table_{table}",
                )
            else:
                st.caption("(empty)")

    st.divider()

    # --- External Data ---
    st.subheader("External NFL Data")
    ext_files = list(_external_dir.glob("*.parquet")) if _external_dir.exists() else []
    if not ext_files:
        st.info("No external data cached yet. Reload data or run the NFL data fetch script.")
    else:
        for i, pf in enumerate(sorted(ext_files)):
            c1, c2, c3 = st.columns([2, 1, 2])
            try:
                ext_df = pd.read_parquet(pf)
                with c1:
                    st.markdown(f"**{pf.stem}**")
                with c2:
                    st.caption(f"{len(ext_df):,} rows")
                with c3:
                    st.download_button(
                        f"⬇️ {pf.stem}.csv",
                        ext_df.to_csv(index=False).encode("utf-8"),
                        f"{pf.stem}.csv", "text/csv",
                        key=f"dl_ext_{pf.stem}",
                    )
            except Exception as exc:
                with c1:
                    st.error(f"{pf.name}: {exc}")

    st.divider()

    # --- Analytics Results ---
    st.subheader("Analytics Results")

    matchups_df = _safe_read(conn, "matchups")

    # Career standings
    if not matchups_df.empty:
        c1, c2, c3 = st.columns([2, 1, 2])
        try:
            career = career_standings(matchups_df)
            with c1:
                st.markdown("**career_standings**")
            with c2:
                st.caption(f"{len(career):,} rows")
            with c3:
                st.download_button(
                    "⬇️ career_standings.csv",
                    career.to_csv(index=False).encode("utf-8"),
                    "career_standings.csv", "text/csv",
                    key="dl_analytics_career",
                )
        except Exception as exc:
            st.error(f"Career standings error: {exc}")

    # All matchups CSV
    if not matchups_df.empty:
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            st.markdown("**all_matchups**")
        with c2:
            st.caption(f"{len(matchups_df):,} rows")
        with c3:
            st.download_button(
                "⬇️ all_matchups.csv",
                matchups_df.to_csv(index=False).encode("utf-8"),
                "all_matchups.csv", "text/csv",
                key="dl_analytics_matchups",
            )

    # Draft picks + VORP (if available)
    draft_df = _safe_read(conn, "draft_picks")
    rosters_df = _safe_read(conn, "rosters")
    if not draft_df.empty:
        c1, c2, c3 = st.columns([2, 1, 2])
        try:
            from fantasy.analytics.draft_analytics import draft_pick_value

            vorp_rows = []
            for season in sorted(draft_df["season"].unique()):
                s_df = draft_pick_value(draft_df, rosters_df, int(season))
                vorp_rows.append(s_df)
            if vorp_rows:
                vorp_df = pd.concat(vorp_rows, ignore_index=True)
                with c1:
                    st.markdown("**draft_picks_with_vorp**")
                with c2:
                    st.caption(f"{len(vorp_df):,} rows")
                with c3:
                    st.download_button(
                        "⬇️ draft_picks_vorp.csv",
                        vorp_df.to_csv(index=False).encode("utf-8"),
                        "draft_picks_vorp.csv", "text/csv",
                        key="dl_analytics_vorp",
                    )
        except ImportError:
            with c1:
                st.markdown("**draft_picks** (no VORP — analytics module not loaded)")
            with c2:
                st.caption(f"{len(draft_df):,} rows")
            with c3:
                st.download_button(
                    "⬇️ draft_picks.csv",
                    draft_df.to_csv(index=False).encode("utf-8"),
                    "draft_picks.csv", "text/csv",
                    key="dl_analytics_draft",
                )
        except Exception as exc:
            st.warning(f"VORP calculation error: {exc}")
            with c3:
                st.download_button(
                    "⬇️ draft_picks.csv",
                    draft_df.to_csv(index=False).encode("utf-8"),
                    "draft_picks.csv", "text/csv",
                    key="dl_analytics_draft_fallback",
                )
