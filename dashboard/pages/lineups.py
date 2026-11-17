"""Lineup efficiency page: optimal vs actual starters, bench points left."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

try:
    from fantasy.analytics.lineups import bench_strength, lineup_efficiency, lineup_efficiency_summary

    _has_lineup_analytics = True
except ImportError:
    _has_lineup_analytics = False


@st.cache_data
def _rosters(_conn) -> pd.DataFrame:
    """Load roster data.

    Args:
        _conn: DuckDB connection.

    Returns:
        Rosters DataFrame.
    """
    return _conn.execute("SELECT * FROM rosters").df()


def render(conn) -> None:
    """Render the Lineup Analysis page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏃 Lineup Analysis")

    if not _has_lineup_analytics:
        st.warning("Lineup analytics module not found. Ensure `src/fantasy/analytics/lineups.py` exists.")
        return

    rosters_df = _rosters(conn)
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()
    league_id: str | None = st.session_state.get("selected_league_id")

    seasons = sorted(rosters_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_opts = ["All Seasons"] + [f"{s} ({provider_map.get(s,'?')})" for s in seasons]

    col1, col2 = st.columns(2)
    with col1:
        season_label = st.selectbox("Season", season_opts, index=len(season_opts) - 1)
    selected_season: int | None = None if season_label == "All Seasons" else seasons[season_opts.index(season_label) - 1]

    if league_id and "league_id" in rosters_df.columns:
        rosters_df = rosters_df[rosters_df["league_id"] == league_id].copy()
    if selected_season is not None:
        season_rosters = rosters_df[rosters_df["season"] == selected_season].copy()
    else:
        season_rosters = rosters_df.copy()

    if season_rosters.empty:
        st.info("No roster data for this selection.")
        return

    tab1, tab2, tab3 = st.tabs(["Efficiency Summary", "Weekly Efficiency", "Bench Strength"])

    with tab1:
        st.subheader("Lineup Efficiency Summary")
        st.caption(
            "Efficiency = actual starter points / optimal possible points. "
            "Points left on bench = how many points were sitting unused."
        )
        summary = lineup_efficiency_summary(season_rosters, selected_season, league_id)
        if summary.empty:
            st.info("No lineup data available.")
        else:
            summary["avg_efficiency"] = (summary["avg_efficiency"] * 100).round(1)
            summary["avg_points_left"] = summary["avg_points_left"].round(2)
            summary["total_points_left"] = summary["total_points_left"].round(2)
            display = summary.rename(columns={
                "owner": "Manager",
                "avg_efficiency": "Avg Efficiency (%)",
                "avg_points_left": "Avg Pts Left/Wk",
                "total_points_left": "Total Pts Left",
                "worst_week_left": "Worst Wk",
                "best_week_left": "Best Wk",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Efficiency Summary CSV",
                display.to_csv(index=False).encode("utf-8"),
                f"lineup_efficiency_{selected_season or 'all'}.csv",
                "text/csv", key="dl_lineup_summary",
            )

            # Bar chart
            fig = px.bar(
                summary.sort_values("avg_efficiency", ascending=False),
                x="owner", y="avg_efficiency",
                labels={"owner": "Manager", "avg_efficiency": "Avg Efficiency (%)"},
                color="avg_efficiency", color_continuous_scale="RdYlGn",
                title="Average Lineup Efficiency by Manager",
            )
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Weekly Lineup Efficiency")
        if selected_season is None:
            st.info("Select a specific season to see weekly efficiency.")
        else:
            eff_df = lineup_efficiency(season_rosters, selected_season, league_id)
            if eff_df.empty:
                st.info("No weekly efficiency data available.")
            else:
                eff_df["efficiency_pct"] = (eff_df["efficiency"] * 100).round(1)
                fig2 = px.bar(
                    eff_df, x="week", y="efficiency_pct", color="owner",
                    barmode="group",
                    labels={"week": "Week", "efficiency_pct": "Efficiency (%)", "owner": "Manager"},
                    title=f"{selected_season} Weekly Lineup Efficiency",
                )
                st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Points Left on Bench by Week")
                fig3 = px.scatter(
                    eff_df, x="week", y="points_left_on_bench", color="owner",
                    labels={"week": "Week", "points_left_on_bench": "Pts Left on Bench", "owner": "Manager"},
                    title=f"{selected_season} Points Left on Bench",
                )
                st.plotly_chart(fig3, use_container_width=True)
                st.download_button(
                    "⬇️ Download Weekly Efficiency CSV",
                    eff_df.to_csv(index=False).encode("utf-8"),
                    f"weekly_efficiency_{selected_season}.csv",
                    "text/csv", key="dl_lineup_weekly",
                )

    with tab3:
        st.subheader("Bench Strength")
        bench_df = bench_strength(season_rosters, selected_season, league_id)
        if bench_df.empty:
            st.info("No bench data available.")
        else:
            bench_summary = bench_df.groupby("owner").agg(
                avg_bench=("bench_points", "mean"),
                avg_starter=("starter_points", "mean"),
            ).reset_index()
            bench_summary["bench_ratio"] = (bench_summary["avg_bench"] / bench_summary["avg_starter"].replace(0, pd.NA)).round(3)
            bench_summary = bench_summary.round(2)
            bench_display = bench_summary.rename(columns={
                "owner": "Manager",
                "avg_bench": "Avg Bench Pts",
                "avg_starter": "Avg Starter Pts",
                "bench_ratio": "Bench/Starter Ratio",
            })
            st.dataframe(bench_display, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Bench Strength CSV",
                bench_display.to_csv(index=False).encode("utf-8"),
                f"bench_strength_{selected_season or 'all'}.csv",
                "text/csv", key="dl_lineup_bench",
            )
