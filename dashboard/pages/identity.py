"""Manager identity management: canonical profiles, merging, and auto-suggestions."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.database.db import update_identity_tables
from fantasy.identity.registry import auto_suggest_merges, load_registry, merge_owners, save_registry

_identity_path = Path(__file__).parents[2] / "data" / "identity" / "manager_aliases.json"


def _get_registry() -> dict:
    """Return the canonical manager registry from disk."""
    return load_registry(_identity_path)


def _all_raw_owners(conn) -> pd.DataFrame:
    """Return all unique raw owners across all leagues with canonical mapping.

    Args:
        conn: Open DuckDB connection.

    Returns:
        DataFrame with league_id, owner_id, name, canonical_id, canonical_display.
    """
    owners_df = conn.execute("SELECT * FROM owners").df()
    registry = _get_registry()
    # Build mapping (league_id, owner_id) → canonical
    id_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for manager in registry.get("canonical_managers", []):
        for alias in manager.get("aliases", []):
            key = (alias.get("league_id", ""), alias.get("raw_owner_id", ""))
            id_lookup[key] = (manager["canonical_id"], manager["display_name"])

    league_col = "league_id" if "league_id" in owners_df.columns else None

    def _resolve(row) -> tuple[str, str]:
        lid = row[league_col] if league_col else ""
        return id_lookup.get((lid, row["owner_id"]), ("", "— Unmerged —"))

    resolved = owners_df.apply(_resolve, axis=1)
    owners_df["canonical_id"] = [r[0] for r in resolved]
    owners_df["canonical_display"] = [r[1] for r in resolved]
    return owners_df


def render(conn) -> None:
    """Render the Manager Identity management page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🪪 Manager Identity")
    st.caption("Merge duplicate owner profiles across leagues or seasons into one canonical manager.")

    tab_all, tab_merge, tab_auto = st.tabs(["All Managers", "Merge Profiles", "Auto-Suggestions"])

    with tab_all:
        _render_all_managers(conn)

    with tab_merge:
        _render_merge(conn)

    with tab_auto:
        _render_auto_suggestions(conn)


def _render_all_managers(conn) -> None:
    """Render the All Managers tab.

    Args:
        conn: Open DuckDB connection.
    """
    owners_df = _all_raw_owners(conn)
    league_col = "league_id" if "league_id" in owners_df.columns else None

    search = st.text_input("Search by name", placeholder="Type to filter…")
    display = owners_df.copy()
    if search:
        display = display[display["name"].str.contains(search, case=False, na=False)]

    cols = ["name", "owner_id", "canonical_display"]
    if league_col:
        cols = [league_col] + cols
    display = display[cols].rename(columns={
        "name": "Raw Name",
        "owner_id": "Owner ID",
        "canonical_display": "Canonical Profile",
        league_col or "": "League",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(f"{len(owners_df)} total raw owner records across all leagues")


def _render_merge(conn) -> None:
    """Render the Merge Profiles tab.

    Args:
        conn: Open DuckDB connection.
    """
    st.subheader("Merge two or more owners into one canonical manager")

    owners_df = _all_raw_owners(conn)
    matchups_df = conn.execute("SELECT * FROM matchups").df()

    league_col = "league_id" if "league_id" in owners_df.columns else None

    def _label(row) -> str:
        league = f"[{row[league_col]}] " if league_col else ""
        return f"{league}{row['name']} ({row['owner_id'][:8]}…)"

    owner_labels = owners_df.apply(_label, axis=1).tolist()
    owner_map = dict(zip(owner_labels, zip(strict=False), strict=False))
    # Build label → row mapping
    label_to_row: dict[str, pd.Series] = {lbl: owners_df.iloc[i] for i, lbl in enumerate(owner_labels)}

    col1, col2 = st.columns(2)
    with col1:
        sel_a = st.selectbox("Owner A", owner_labels, key="merge_a")
    with col2:
        remaining = [l for l in owner_labels if l != sel_a]
        sel_b = st.selectbox("Owner B", remaining, key="merge_b")

    row_a = label_to_row[sel_a]
    row_b = label_to_row[sel_b]

    # Side-by-side stats
    def _owner_stats(owner_name: str, owner_id: str) -> dict:
        a_mask = matchups_df["team_a_owner"] == owner_name
        b_mask = matchups_df["team_b_owner"] == owner_name
        a_rows = matchups_df[a_mask]
        b_rows = matchups_df[b_mask]
        all_pts = pd.concat([
            a_rows["points_a"].rename("pts"),
            b_rows["points_b"].rename("pts"),
        ]).dropna()
        wins = (a_rows["winner_team_id"] == a_rows["team_a_id"]).sum() + \
               (b_rows["winner_team_id"] == b_rows["team_b_id"]).sum()
        losses = (a_rows["winner_team_id"] != a_rows["team_a_id"]).sum() + \
                 (b_rows["winner_team_id"] != b_rows["team_b_id"]).sum()
        return {
            "Name": owner_name,
            "Leagues": matchups_df[a_mask | b_mask]["league_id"].nunique() if "league_id" in matchups_df.columns else 1,
            "Seasons": matchups_df[a_mask | b_mask]["season"].nunique(),
            "W-L": f"{wins}-{losses}",
            "Avg Score": f"{all_pts.mean():.1f}" if not all_pts.empty else "N/A",
            "Games": len(all_pts),
        }

    stats_a = _owner_stats(row_a["name"], row_a["owner_id"])
    stats_b = _owner_stats(row_b["name"], row_b["owner_id"])

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**{row_a['name']}**")
        for k, v in stats_a.items():
            st.markdown(f"- {k}: {v}")
    with c2:
        st.markdown(f"**{row_b['name']}**")
        for k, v in stats_b.items():
            st.markdown(f"- {k}: {v}")

    st.divider()
    display_name = st.text_input(
        "Canonical display name for merged profile",
        value=row_a["name"],
        key="merge_display_name",
    )

    if st.button("Merge into one canonical manager", type="primary"):
        if not display_name.strip():
            st.error("Enter a display name.")
            return

        registry = _get_registry()
        aliases = [
            {
                "league_id": row_a.get(league_col, "") if league_col else "",
                "raw_owner_id": row_a["owner_id"],
                "raw_name": row_a["name"],
            },
            {
                "league_id": row_b.get(league_col, "") if league_col else "",
                "raw_owner_id": row_b["owner_id"],
                "raw_name": row_b["name"],
            },
        ]
        registry, new_id = merge_owners(registry, aliases, display_name.strip())
        save_registry(registry, _identity_path)
        update_identity_tables(conn, registry)
        st.cache_data.clear()
        st.success(f"Merged → canonical ID `{new_id}` with display name **{display_name}**")
        st.rerun()


def _render_auto_suggestions(conn) -> None:
    """Render the Auto-Suggestions tab.

    Args:
        conn: Open DuckDB connection.
    """
    st.subheader("Automatically suggested duplicate profiles")
    st.caption("Pairs with ≥ 80% name similarity. Accept to merge them.")

    owners_df = _all_raw_owners(conn)
    league_col = "league_id" if "league_id" in owners_df.columns else None

    suggest_df = owners_df.rename(columns={
        "owner_id": "raw_owner_id",
        "name": "raw_name",
    })
    if league_col is None:
        suggest_df["league_id"] = ""

    suggestions = auto_suggest_merges(suggest_df)

    if not suggestions:
        st.info("No similar-name pairs found above the 80% similarity threshold.")
        return

    df = pd.DataFrame(suggestions)
    df.insert(0, "Accept", False)
    df["similarity_pct"] = (df["similarity"] * 100).round(1).astype(str) + "%"
    display_cols = ["Accept", "name_a", "league_a", "name_b", "league_b", "similarity_pct"]
    edited = st.data_editor(
        df[display_cols].rename(columns={
            "name_a": "Name A", "league_a": "League A",
            "name_b": "Name B", "league_b": "League B",
            "similarity_pct": "Similarity",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={"Accept": st.column_config.CheckboxColumn()},
    )

    accepted_idx = edited[edited["Accept"]].index.tolist()
    if not accepted_idx:
        st.caption("Check rows above to accept suggestions, then click Apply.")
        return

    st.write(f"{len(accepted_idx)} merge(s) selected.")
    if st.button("Apply selected merges", type="primary"):
        registry = _get_registry()
        for idx in accepted_idx:
            row = suggestions[idx]
            aliases = [
                {
                    "league_id": row["league_a"],
                    "raw_owner_id": row["owner_id_a"],
                    "raw_name": row["name_a"],
                },
                {
                    "league_id": row["league_b"],
                    "raw_owner_id": row["owner_id_b"],
                    "raw_name": row["name_b"],
                },
            ]
            registry, _ = merge_owners(registry, aliases, row["name_a"])
        save_registry(registry, _identity_path)
        update_identity_tables(conn, registry)
        st.cache_data.clear()
        st.success(f"Applied {len(accepted_idx)} merge(s).")
        st.rerun()
