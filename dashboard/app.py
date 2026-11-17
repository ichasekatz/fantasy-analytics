"""Main Streamlit application entry point for Bigwell's Leaguern Analytics."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from fantasy.database.db import load_from_export, reload_all_leagues
from style import inject_css

_project_root = Path(__file__).parents[1]
_export_path = _project_root / "data" / "raw" / "bigwell-s-leaguern-fantasy-hall-of-fame-export.json"
_original_export = Path(__file__).parents[2] / "bigwell-s-leaguern-fantasy-hall-of-fame-export.json"
_db_path = _project_root / "data" / "database" / "fantasy.duckdb"
_leagues_config_path = _project_root / "config" / "leagues.json"


@st.cache_resource
def _get_conn():
    """Return a cached DuckDB connection, initializing from all registered leagues."""
    source = _export_path if _export_path.exists() else _original_export
    return load_from_export(source, _db_path)


def _load_league_options() -> dict[str, str | None]:
    """Load league names from the registry for the sidebar selector.

    Non-primary leagues (filtered views of another entry) are shown with a
    suffix so it's clear they share data with a primary league.

    Returns:
        Ordered dict mapping display label → league_id (None for 'All Leagues').
    """
    options: dict[str, str | None] = {"All Leagues (no double-counting)": None}
    try:
        config = json.loads(_leagues_config_path.read_text(encoding="utf-8"))
        for entry in config.get("leagues", []):
            label = entry["name"]
            if not entry.get("primary", True):
                label += " ↳"  # visual hint: sub-view of another league
            options[label] = entry["league_id"]
    except (OSError, json.JSONDecodeError):
        pass
    return options


st.set_page_config(
    page_title="Bigwell's Leaguern Analytics",
    page_icon="🏈",
    layout="wide",
)

conn = _get_conn()
inject_css()

# Seed canonical name map once per session so all pages resolve aliases
if "_name_map" not in st.session_state:
    from utils import build_name_map
    st.session_state["_name_map"] = build_name_map(conn)

pages = {
    # --- Core ---
    "🏠 Overview": "overview",
    "🏛️ Hall of Fame": "hall_of_fame",
    "📈 Season Explorer": "season_explorer",
    "🎁 Fantasy Wrapped": "season_recap",
    "📅 Matchups": "matchups",
    "📊 Standings": "standings",
    # --- Managers ---
    "👤 Managers": "managers",
    "🏈 Player Stats": "player_stats",
    "📐 Manager Comparison": "comparison",
    "⚔️ Head-to-Head": "headtohead",
    "🔥 Rivalries": "rivalries",
    "📊 Power Rankings": "power_rankings",
    "📊 Dynamic Rankings": "dynamic_rankings",
    # --- Draft ---
    "🎯 Draft Board": "draft",
    "🧬 Draft DNA": "draft_dna",
    # --- Season Analysis ---
    "🍀 Luck Analysis": "luck",
    "📅 Schedule Simulator": "schedule_sim",
    "🎲 Playoff Odds": "playoff_odds",
    # --- Players ---
    "🔍 Player Explorer": "player_explorer",
    "👑 Player Ownership": "player_ownership",
    "🌟 Player Hall of Fame": "player_hof",
    # --- Decisions ---
    "🔄 Trade Lab": "trades",
    "🏃 Lineup Analysis": "lineups",
    "🩺 Injury Impact": "injuries",
    # --- History ---
    "🏆 All-Time Records": "alltime",
    "🥇 Awards": "awards",
    "🧠 Trivia": "trivia",
    "🔬 Custom Analytics": "custom_analytics",
    # --- Admin ---
    "⬇️ Downloads": "downloads",
    "🪪 Manager Identity": "identity",
    "⚙️ League Config": "league_config",
}

league_options = _load_league_options()

with st.sidebar:
    st.title("🏈 Bigwell's Leaguern")
    st.caption("Historical Fantasy Analytics")
    st.divider()

    # League selector
    selected_league_label = st.selectbox(
        "League",
        list(league_options.keys()),
        index=0,
        help="Filter all pages to a specific league, or view across all leagues.",
    )
    st.session_state["selected_league_id"] = league_options[selected_league_label]

    # Format filter — only relevant when viewing All Leagues
    if league_options[selected_league_label] is None:
        fmt_label = st.radio(
            "Format",
            ["Redraft Only", "Dynasty Only", "All Formats"],
            index=0,
            horizontal=True,
            help="foxs-pizza-den-dynasty is the dynasty league.",
        )
        fmt_map = {"Redraft Only": "redraft_only", "Dynasty Only": "dynasty_only", "All Formats": "all"}
        st.session_state["league_format"] = fmt_map[fmt_label]
    else:
        st.session_state["league_format"] = "all"

    st.divider()

    selected = st.radio("Navigate", list(pages.keys()), label_visibility="collapsed")
    st.divider()

    if st.button("🔄 Reload Data"):
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()

    st.caption(
        "To add a new league: drop its export JSON in `data/raw/`, "
        "register it in `config/leagues.json`, then click Reload Data."
    )

page_module = pages[selected]
mod = importlib.import_module(f"views.{page_module}")
mod.render(conn)
