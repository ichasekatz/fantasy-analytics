"""Player explorer: cross-league player performance, name merging, and NFL stats."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.players import (
    cross_league_top_scorers,
    player_career,
    player_season_breakdown,
    player_weekly_scores,
)
from fantasy.identity.player_registry import (
    apply_player_registry,
    auto_suggest_player_merges,
    load_player_registry,
    merge_player_names,
    save_player_registry,
)

_ext_seasonal = Path(__file__).parents[2] / "data" / "external" / "nfl_seasonal_stats.parquet"
_registry_path = Path(__file__).parents[2] / "data" / "identity" / "player_aliases.json"
_all_positions = ["QB", "RB", "WR", "TE", "K", "DST"]


@st.cache_data
def _load_rosters(_conn) -> pd.DataFrame:
    """Load all roster data.

    Args:
        _conn: DuckDB connection.

    Returns:
        Rosters DataFrame.
    """
    return _conn.execute("SELECT * FROM rosters").df()


@st.cache_data
def _load_draft_picks(_conn) -> pd.DataFrame:
    """Load draft picks.

    Args:
        _conn: DuckDB connection.

    Returns:
        Draft picks DataFrame.
    """
    return _conn.execute("SELECT * FROM draft_picks").df()


def _apply_registry_cached(rosters_df: pd.DataFrame, draft_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the player registry to normalize player names.

    Args:
        rosters_df: Raw rosters DataFrame.
        draft_df: Raw draft picks DataFrame.

    Returns:
        Tuple of (rosters_df_normalized, draft_df_normalized).
    """
    registry = load_player_registry(_registry_path)
    r = apply_player_registry(rosters_df, registry)
    d = apply_player_registry(draft_df, registry)
    return r, d


def render(conn) -> None:
    """Render the Player Explorer page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🔍 Player Explorer")

    raw_rosters = _load_rosters(conn)
    raw_drafts = _load_draft_picks(conn)
    rosters_df, draft_df = _apply_registry_cached(raw_rosters, raw_drafts)

    # Player Explorer is cross-league by design — sidebar filter ignored here.
    # Users can filter by season or position within the page instead.

    all_names = sorted(rosters_df["player"].unique())
    seasons = sorted(rosters_df["season"].unique())

    tab_search, tab_top, tab_merge, tab_suggest = st.tabs([
        "🔎 Player Search", "🏆 Top Scorers", "✏️ Merge Names", "🤖 Auto-Suggest Merges",
    ])

    # ── Tab 1: Player Search ─────────────────────────────────────────────────
    with tab_search:
        col1, col2, col3 = st.columns([3, 2, 2])
        with col1:
            search = st.text_input("Search player name", placeholder="e.g. Patrick Mahomes")
        with col2:
            pos_filter = st.multiselect("Position", _all_positions, default=_all_positions, key="ps_pos")
        with col3:
            season_opts = ["All Seasons"] + [str(s) for s in seasons]
            season_sel = st.selectbox("Season", season_opts, key="ps_season")
        selected_season: int | None = None if season_sel == "All Seasons" else int(season_sel)

        filtered = rosters_df.copy()
        if search.strip():
            filtered = filtered[filtered["player"].str.contains(search.strip(), case=False, na=False)]
        if pos_filter:
            filtered = filtered[filtered["position"].isin(pos_filter)]
        if selected_season is not None:
            filtered = filtered[filtered["season"] == selected_season]

        if not search.strip():
            st.info("Enter a player name above to explore their stats across all leagues.")
        elif filtered.empty:
            st.warning(f"No results for '{search}'.")
        else:
            matched_players = filtered["player"].unique()

            # Cross-league career card for each matched player
            for pname in matched_players[:5]:
                breakdown = player_season_breakdown(rosters_df, draft_df, pname)
                if breakdown.empty:
                    continue

                total_pts = breakdown["total_points"].sum()
                leagues = breakdown["league_id"].nunique()
                seasons_count = breakdown["season"].nunique()

                with st.expander(f"**{pname}** — {total_pts:.1f} pts across {leagues} league(s), {seasons_count} season(s)", expanded=len(matched_players) == 1):
                    # Summary metrics
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Total Points", f"{total_pts:.1f}")
                    mc2.metric("Leagues", leagues)
                    mc3.metric("Seasons", seasons_count)
                    best_avg = breakdown["avg_per_start"].max()
                    mc4.metric("Best Avg/Start", f"{best_avg:.1f}" if pd.notna(best_avg) else "—")

                    # Season-by-season breakdown table
                    disp_cols = ["league_id", "season", "owner_name", "team_name",
                                 "total_points", "starter_weeks", "avg_per_start",
                                 "was_drafted", "draft_round", "was_keeper"]
                    disp = breakdown[[c for c in disp_cols if c in breakdown.columns]].rename(columns={
                        "league_id": "League", "season": "Season", "owner_name": "Owner",
                        "team_name": "Team", "total_points": "Total Pts",
                        "starter_weeks": "Starts", "avg_per_start": "Avg/Start",
                        "was_drafted": "Drafted", "draft_round": "Rd", "was_keeper": "Keeper",
                    })
                    st.dataframe(disp, use_container_width=True, hide_index=True)

                    # Weekly scoring chart
                    weekly = player_weekly_scores(rosters_df, pname)
                    if not weekly.empty and len(weekly) > 1:
                        weekly["label"] = weekly["league_id"].str[:12] + " " + weekly["season"].astype(str) + " W" + weekly["week"].astype(str)
                        fig = px.bar(
                            weekly,
                            x="label", y="points",
                            color="league_id",
                            title=f"{pname} — Weekly Fantasy Points",
                            labels={"label": "Week", "points": "Points", "league_id": "League"},
                        )
                        fig.update_layout(xaxis_tickangle=-45, height=300)
                        st.plotly_chart(fig, use_container_width=True)

                    # External NFL stats
                    if _ext_seasonal.exists():
                        try:
                            nfl = pd.read_parquet(_ext_seasonal)
                            nfl_match = nfl[nfl["player_name"].str.contains(search.strip(), case=False, na=False)]
                            if not nfl_match.empty:
                                st.caption("📊 NFL Stats (via nfl_data_py)")
                                show_cols = [c for c in [
                                    "season", "player_name", "position", "recent_team",
                                    "fantasy_points_ppr", "passing_yards", "passing_tds",
                                    "rushing_yards", "rushing_tds",
                                    "receptions", "targets", "receiving_yards", "receiving_tds",
                                ] if c in nfl_match.columns]
                                st.dataframe(nfl_match[show_cols].sort_values("season"), use_container_width=True, hide_index=True)
                        except Exception:
                            pass

            if len(matched_players) > 5:
                st.caption(f"Showing first 5 of {len(matched_players)} matched players. Refine your search.")

    # ── Tab 2: Top Scorers ───────────────────────────────────────────────────
    with tab_top:
        col1, col2, col3 = st.columns(3)
        with col1:
            top_pos = st.selectbox("Position", ["All"] + _all_positions, key="top_pos")
        with col2:
            top_season_opts = ["All Seasons"] + [str(s) for s in seasons]
            top_season = st.selectbox("Season", top_season_opts, key="top_season")
        with col3:
            top_n = st.number_input("Show top N", min_value=5, max_value=100, value=25, step=5)

        pos_arg = None if top_pos == "All" else top_pos
        season_arg = None if top_season == "All Seasons" else int(top_season)

        top_df = cross_league_top_scorers(rosters_df, position=pos_arg, season=season_arg, top_n=int(top_n))
        if not top_df.empty:
            top_df.insert(0, "Rank", range(1, len(top_df) + 1))
            top_df["total_points"] = top_df["total_points"].round(1)
            top_df["avg_per_start"] = top_df["avg_per_start"].round(2)
            st.dataframe(top_df.rename(columns={
                "player": "Player", "position": "Pos", "total_points": "Total Pts",
                "starter_weeks": "Starts", "avg_per_start": "Avg/Start",
                "leagues_played": "Leagues", "seasons_played": "Seasons",
            }), use_container_width=True, hide_index=True)

            fig = px.bar(
                top_df.head(20),
                x="player", y="total_points", color="position",
                title=f"Top {min(20, len(top_df))} Fantasy Scorers",
                labels={"player": "Player", "total_points": "Total Points"},
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)

    # ── Tab 3: Merge Names ───────────────────────────────────────────────────
    with tab_merge:
        st.subheader("Merge Player Names")
        st.caption("Use this when the same player appears under different names in different leagues or seasons (e.g. 'OBJ' vs 'Odell Beckham Jr.').")

        registry = load_player_registry(_registry_path)

        # Show current merges
        if registry["canonical_players"]:
            existing_rows = []
            for entry in registry["canonical_players"]:
                aliases = [a["raw_name"] for a in entry.get("aliases", [])]
                existing_rows.append({
                    "Canonical Name": entry["display_name"],
                    "Position": entry.get("position", ""),
                    "Aliases": ", ".join(aliases) if aliases else "—",
                })
            st.dataframe(pd.DataFrame(existing_rows), use_container_width=True, hide_index=True)
            st.divider()

        st.markdown("**Add a new merge:**")
        col_a, col_b = st.columns(2)
        with col_a:
            name_a = st.selectbox("Name A (keep this as canonical)", [""] + all_names, key="merge_a")
        with col_b:
            name_b = st.selectbox("Name B (alias — merge into A)", [""] + all_names, key="merge_b")

        canonical_override = st.text_input(
            "Canonical display name (leave blank to use Name A)",
            key="merge_canonical",
        )
        pos_hint = st.selectbox("Position hint (optional)", [""] + _all_positions, key="merge_pos")

        if st.button("✅ Merge These Names", disabled=not (name_a and name_b and name_a != name_b)):
            canonical = canonical_override.strip() or name_a
            updated = merge_player_names(registry, [name_a, name_b], canonical, position=pos_hint)
            save_player_registry(updated, _registry_path)
            st.cache_data.clear()
            st.success(f"Merged '{name_a}' and '{name_b}' → '{canonical}'. Reload the page to see updated stats.")
            st.rerun()

    # ── Tab 4: Auto-Suggest Merges ───────────────────────────────────────────
    with tab_suggest:
        st.subheader("Auto-Suggested Name Merges")
        st.caption("Fuzzy-matched player names that might be the same person. Review and accept any that apply.")

        if st.button("🔍 Run Fuzzy Matching"):
            with st.spinner("Scanning all player names..."):
                suggestions = auto_suggest_player_merges(all_names, threshold=0.82)
            st.session_state["player_suggestions"] = suggestions

        suggestions = st.session_state.get("player_suggestions", [])
        if not suggestions:
            st.info("Click 'Run Fuzzy Matching' to scan for similar player names.")
        else:
            registry = load_player_registry(_registry_path)
            lookup = {a["raw_name"] for e in registry["canonical_players"] for a in e.get("aliases", [])}
            lookup |= {e["display_name"] for e in registry["canonical_players"]}

            already_merged = {
                (min(a, b), max(a, b))
                for e in registry["canonical_players"]
                for a in [e["display_name"]] + [x["raw_name"] for x in e.get("aliases", [])]
                for b in [e["display_name"]] + [x["raw_name"] for x in e.get("aliases", [])]
                if a != b
            }

            pending = [
                s for s in suggestions
                if (min(s["name_a"], s["name_b"]), max(s["name_a"], s["name_b"])) not in already_merged
            ]

            st.caption(f"{len(pending)} suggestions (excluding already-merged pairs)")
            for i, sug in enumerate(pending[:30]):
                col1, col2, col3, col4 = st.columns([3, 3, 1, 2])
                col1.write(sug["name_a"])
                col2.write(sug["name_b"])
                col3.write(f"{sug['similarity']:.0%}")
                if col4.button("Merge →", key=f"sug_{i}"):
                    reg = load_player_registry(_registry_path)
                    updated = merge_player_names(reg, [sug["name_a"], sug["name_b"]], sug["name_a"])
                    save_player_registry(updated, _registry_path)
                    st.cache_data.clear()
                    st.success(f"Merged '{sug['name_b']}' into '{sug['name_a']}'")
                    st.rerun()
