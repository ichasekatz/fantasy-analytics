"""Head-to-head matchup history between two managers, with cross-league support."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.identity.enrichment import enrich_matchups
from fantasy.identity.registry import load_registry
from utils import apply_league_filter

_identity_path = Path(__file__).parents[2] / "data" / "identity" / "manager_aliases.json"


def render(conn) -> None:
    """Render the Head-to-Head page.

    Uses canonical display names when available. When "All Leagues" is selected,
    searches across every registered league.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("⚔️ Head-to-Head")

    registry = load_registry(_identity_path)
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups ORDER BY season, week").df())

    enriched = enrich_matchups(matchups_df, registry)

    # Manager list: canonical display names (falls back to raw owner names)
    all_managers = sorted(set(
        enriched["canonical_display_a"].dropna().tolist()
        + enriched["canonical_display_b"].dropna().tolist()
    ))

    col1, col2 = st.columns(2)
    with col1:
        manager_a = st.selectbox("Manager A", all_managers, index=0)
    with col2:
        remaining = [m for m in all_managers if m != manager_a]
        manager_b = st.selectbox("Manager B", remaining, index=0)

    if manager_a == manager_b:
        st.warning("Select two different managers.")
        return

    # Find all matchups between them using canonical display names
    h2h = enriched[
        ((enriched["canonical_display_a"] == manager_a) & (enriched["canonical_display_b"] == manager_b))
        | ((enriched["canonical_display_a"] == manager_b) & (enriched["canonical_display_b"] == manager_a))
    ].copy()

    if h2h.empty:
        st.info("No matchups found between these two managers.")
        return

    # Normalize so manager_a is always "left"
    rows = []
    for _, row in h2h.iterrows():
        is_a_left = row["canonical_display_a"] == manager_a
        pts_a = row["points_a"] if is_a_left else row["points_b"]
        pts_b = row["points_b"] if is_a_left else row["points_a"]
        team_a = row["team_a_name"] if is_a_left else row["team_b_name"]
        team_b = row["team_b_name"] if is_a_left else row["team_a_name"]

        if row["winner_team_id"] == row["team_a_id"]:
            winner = row["canonical_display_a"]
        elif row["winner_team_id"] == row["team_b_id"]:
            winner = row["canonical_display_b"]
        else:
            winner = "Tie"

        rows.append({
            "season": row["season"],
            "week": row.get("week"),
            "league_id": row.get("league_id", ""),
            "team_a": team_a,
            "pts_a": pts_a,
            "pts_b": pts_b,
            "team_b": team_b,
            "winner": winner,
            "is_playoff": row["is_playoff"],
            "is_championship": row["is_championship"],
        })

    norm = pd.DataFrame(rows)

    wins_a = (norm["winner"] == manager_a).sum()
    wins_b = (norm["winner"] == manager_b).sum()
    ties = (norm["winner"] == "Tie").sum()
    avg_a = norm["pts_a"].mean()
    avg_b = norm["pts_b"].mean()

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{manager_a} Wins", wins_a)
    c2.metric("Total Matchups", len(norm))
    c3.metric(f"{manager_b} Wins", wins_b)

    c4, c5 = st.columns(2)
    c4.metric(f"{manager_a} Avg Score", f"{avg_a:.2f}" if pd.notna(avg_a) else "N/A")
    c5.metric(f"{manager_b} Avg Score", f"{avg_b:.2f}" if pd.notna(avg_b) else "N/A")
    if ties:
        st.caption(f"Ties: {ties}")

    st.divider()
    st.subheader("All Matchups")

    norm["Type"] = norm["is_championship"].map({True: "🏆 Championship"}).fillna(
        norm["is_playoff"].map({True: "🎯 Playoff"}).fillna("Regular")
    )
    norm["Score"] = norm.apply(
        lambda r: f"{r['pts_a']:.2f} – {r['pts_b']:.2f}" if pd.notna(r["pts_a"]) else "N/A", axis=1
    )

    display_cols = ["season", "week", "Type", "team_a", "Score", "team_b", "winner"]
    rename_map = {
        "season": "Season", "week": "Week",
        "team_a": f"{manager_a} Team",
        "team_b": f"{manager_b} Team",
        "winner": "Winner",
    }
    if st.session_state.get("selected_league_id") is None and "league_id" in norm.columns:
        display_cols = ["league_id"] + display_cols
        rename_map["league_id"] = "League"

    h2h_out = norm[display_cols].rename(columns=rename_map)
    st.dataframe(h2h_out, use_container_width=True, hide_index=True)
