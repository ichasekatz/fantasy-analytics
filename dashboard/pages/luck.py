"""Luck analysis page: expected wins vs actual, schedule difficulty."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.luck import luck_metrics


def render(conn) -> None:
    """Render the Luck Analysis page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🍀 Luck Analysis")
    st.caption(
        "Expected wins = how many wins a team would expect if they played every other team each week. "
        "Luck delta = actual wins − expected wins. Positive = lucky schedule, negative = unlucky."
    )

    matchups_df = conn.execute("SELECT * FROM matchups").df()
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(seasons) - 1)
    selected_season = seasons[season_labels.index(selected_label)]

    luck = luck_metrics(matchups_df, selected_season)

    if luck.empty:
        st.info("No luck data available for this season.")
        return

    # Table
    st.subheader("Expected vs Actual Wins")
    display = luck.copy()
    display["expected_wins"] = display["expected_wins"].round(2)
    display["luck_delta"] = display["luck_delta"].round(2)
    display["schedule_difficulty"] = display["schedule_difficulty"].round(1)
    display = display.rename(columns={
        "owner": "Owner", "team": "Team",
        "actual_wins": "Actual W", "expected_wins": "Expected W",
        "luck_delta": "Luck Δ", "schedule_difficulty": "Opp Avg PF",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download Luck Data CSV",
        display.to_csv(index=False).encode("utf-8"),
        f"luck_{selected_season}.csv", "text/csv",
        key=f"dl_luck_{selected_season}",
    )

    st.divider()

    # Bar chart
    st.subheader("Luck Delta by Manager")
    fig = px.bar(
        luck.sort_values("luck_delta"),
        x="luck_delta", y="owner", orientation="h",
        labels={"luck_delta": "Luck Δ (Actual − Expected Wins)", "owner": "Manager"},
        color="luck_delta",
        color_continuous_scale=["#d62728", "#aec7e8", "#1f77b4"],
        color_continuous_midpoint=0,
    )
    fig.update_layout(showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

    # Schedule difficulty
    st.subheader("Schedule Difficulty (Avg Opponent Score)")
    fig2 = px.bar(
        luck.sort_values("schedule_difficulty", ascending=False),
        x="owner", y="schedule_difficulty",
        labels={"schedule_difficulty": "Avg Opponent Points", "owner": "Manager"},
        color_discrete_sequence=["#ff7f0e"],
    )
    st.plotly_chart(fig2, use_container_width=True)
