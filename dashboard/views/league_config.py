"""League configuration: edit season filters and excluded players per league."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

_project_root = Path(__file__).parents[2]
_leagues_config_path = _project_root / "config" / "leagues.json"


def _load_config() -> dict:
    try:
        return json.loads(_leagues_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"leagues": []}


def _save_config(config: dict) -> None:
    _leagues_config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def render(conn) -> None:
    """Render the League Configuration page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("⚙️ League Config")
    st.caption(
        "Control which seasons are included in each league. "
        "Changes take effect after clicking 'Reload Data' in the sidebar."
    )

    config = _load_config()
    leagues = config.get("leagues", [])
    if not leagues:
        st.error("No leagues registered. Check config/leagues.json.")
        return

    # Get all available seasons per export file
    all_seasons_by_export: dict[str, list[int]] = {}
    try:
        all_matchups = conn.execute("SELECT league_id, season FROM matchups GROUP BY league_id, season ORDER BY season").df()
        for lid, group in all_matchups.groupby("league_id"):
            all_seasons_by_export[str(lid)] = sorted(group["season"].unique().tolist())
    except Exception:
        pass

    changed = False
    updated_leagues = []

    for entry in leagues:
        lid = entry["league_id"]
        name = entry["name"]
        is_primary = entry.get("primary", True)
        current_filter: list[int] | None = entry.get("season_filter")

        # Available seasons for this league (from its league_id in DB)
        available_seasons = all_seasons_by_export.get(lid, [])

        with st.expander(f"**{name}**" + (" *(sub-view)*" if not is_primary else ""), expanded=False):
            st.caption(f"league_id: `{lid}` | primary: `{is_primary}`")
            if entry.get("notes"):
                st.caption(entry["notes"])

            if not available_seasons:
                st.info("No season data loaded yet. Reload data first.")
                updated_leagues.append(entry)
                continue

            st.markdown("**Include these seasons:**")
            st.caption("Uncheck a year to exclude it from this league's data. Useful when seasons diverged into a separate league.")

            new_filter: list[int] = []
            cols = st.columns(min(len(available_seasons), 6))
            for i, season in enumerate(available_seasons):
                col = cols[i % len(cols)]
                with col:
                    included = current_filter is None or season in current_filter
                    checked = st.checkbox(str(season), value=included, key=f"season_{lid}_{season}")
                    if checked:
                        new_filter.append(season)

            # Determine if changed
            old_filter_set = set(current_filter) if current_filter is not None else set(available_seasons)
            new_filter_set = set(new_filter)

            if old_filter_set != new_filter_set:
                changed = True

            # If all seasons included, store null (no filter)
            if set(new_filter) == set(available_seasons):
                entry["season_filter"] = None
            else:
                entry["season_filter"] = sorted(new_filter)

            updated_leagues.append(entry)

            # Show current state
            if entry["season_filter"] is None:
                st.caption("✅ All seasons included")
            elif not entry["season_filter"]:
                st.warning("⚠️ No seasons selected — this league will have no data.")
            else:
                st.caption(f"Included: {', '.join(str(s) for s in entry['season_filter'])}")

        st.divider()

    if changed:
        if st.button("💾 Save Season Config", type="primary"):
            config["leagues"] = updated_leagues
            _save_config(config)
            st.success("Saved. Click 'Reload Data' in the sidebar to apply changes.")
            st.cache_data.clear()
    else:
        st.info("No changes. Edit season checkboxes above, then save.")

    st.divider()

    # --- Player exclusion ---
    st.subheader("Player Exclusions (session only)")
    st.caption(
        "Exclude specific players from stats calculations in this session. "
        "Useful for 'what if' analysis — e.g. standings without Josh Allen. "
        "These are NOT saved and reset on page reload."
    )

    if "excluded_players" not in st.session_state:
        st.session_state["excluded_players"] = []

    try:
        all_players = sorted(conn.execute("SELECT DISTINCT player FROM rosters WHERE player IS NOT NULL ORDER BY player").df()["player"].tolist())
    except Exception:
        all_players = []

    excluded = st.multiselect(
        "Exclude players from all calculations",
        all_players,
        default=st.session_state["excluded_players"],
        help="Stats for these players will be zeroed out / ignored in this session.",
        key="excluded_players_select",
    )
    st.session_state["excluded_players"] = excluded

    if excluded:
        st.warning(f"Currently excluding: {', '.join(excluded)}")
        if st.button("Clear all exclusions"):
            st.session_state["excluded_players"] = []
            st.rerun()
