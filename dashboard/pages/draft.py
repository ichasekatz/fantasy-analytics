"""Draft board page: picks by season, keeper flags, picks-per-team summary."""

from __future__ import annotations

import streamlit as st


def render(conn) -> None:
    """Render the Draft Board page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🎯 Draft Board")

    draft_df = conn.execute("SELECT * FROM draft_picks ORDER BY season, overall").df()
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()

    seasons = sorted(draft_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels)
    selected_season = seasons[season_labels.index(selected_label)]

    season_draft = draft_df[draft_df["season"] == selected_season].copy()

    if season_draft.empty:
        st.info("No draft data available for this season.")
        return

    num_rounds = int(season_draft["round"].max())
    num_teams = len(season_draft["team_id"].unique())
    num_keepers = int(season_draft["keeper"].sum())
    st.caption(f"{num_rounds} rounds · {num_teams} teams · {num_keepers} keeper(s)")

    tab1, tab2 = st.tabs(["Draft Board", "By Manager"])

    with tab1:
        display = season_draft[["overall", "round", "owner_name", "team_name", "player", "position", "keeper", "cost"]].rename(columns={
            "overall": "Pick", "round": "Rd", "owner_name": "Owner",
            "team_name": "Team", "player": "Player", "position": "Pos",
            "keeper": "Keeper", "cost": "Cost",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Draft Board CSV",
            display.to_csv(index=False).encode("utf-8"),
            f"draft_{selected_season}.csv", "text/csv",
            key=f"dl_draft_{selected_season}",
        )

    with tab2:
        managers = sorted(season_draft["owner_name"].dropna().unique())
        selected_mgr = st.selectbox("Manager", managers)
        mgr_picks = season_draft[season_draft["owner_name"] == selected_mgr].copy()

        st.write(f"**{len(mgr_picks)} picks** · **{int(mgr_picks['keeper'].sum())} keepers**")
        display_mgr = mgr_picks[["overall", "round", "player", "position", "keeper", "cost"]].rename(columns={
            "overall": "Pick", "round": "Rd", "player": "Player",
            "position": "Pos", "keeper": "Keeper", "cost": "Cost",
        })
        st.dataframe(display_mgr, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Manager Picks CSV",
            display_mgr.to_csv(index=False).encode("utf-8"),
            f"draft_{selected_season}_{selected_mgr.replace(' ', '_')}.csv",
            "text/csv", key=f"dl_draft_mgr_{selected_season}_{selected_mgr}",
        )

        # Positional breakdown
        pos_counts = mgr_picks["position"].value_counts().reset_index()
        pos_counts.columns = ["Position", "Count"]
        st.subheader("Positional Breakdown")
        st.dataframe(pos_counts, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Positional Breakdown CSV",
            pos_counts.to_csv(index=False).encode("utf-8"),
            f"draft_positions_{selected_season}_{selected_mgr.replace(' ', '_')}.csv",
            "text/csv", key=f"dl_draft_pos_{selected_season}_{selected_mgr}",
        )
