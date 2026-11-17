"""Lineup efficiency page: optimal vs actual starters, bench points left."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from utils import apply_league_filter

try:
    from fantasy.analytics.lineups import bench_strength, lineup_decision_quality, lineup_efficiency, lineup_efficiency_summary

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

    rosters_df = apply_league_filter(_rosters(conn))
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    league_id: str | None = st.session_state.get("selected_league_id")

    seasons = sorted(rosters_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_opts = ["All Seasons"] + [f"{s} ({provider_map.get(s,'?')})" for s in seasons]

    col1, col2 = st.columns(2)
    with col1:
        season_label = st.selectbox("Season", season_opts, index=len(season_opts) - 1)
    selected_season: int | None = None if season_label == "All Seasons" else seasons[season_opts.index(season_label) - 1]
    if selected_season is not None:
        season_rosters = rosters_df[rosters_df["season"] == selected_season].copy()
    else:
        season_rosters = rosters_df.copy()

    if season_rosters.empty:
        st.info("No roster data for this selection.")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["Efficiency Summary", "Weekly Efficiency", "Bench Strength", "🎯 Decision Quality"])

    with tab1:
        st.subheader("Lineup Efficiency Summary")
        st.caption(
            "Efficiency = actual starter points / optimal possible points. "
            "Points left on bench = how many points were sitting unused."
        )
        summary = lineup_efficiency_summary(season_rosters, selected_season, league_id)
        if selected_season is None:
            min_seasons_filter = st.session_state.get("min_seasons_played", 1)
            if min_seasons_filter > 1 and "seasons_played" in summary.columns:
                summary = summary[summary["seasons_played"] >= min_seasons_filter].reset_index(drop=True)
            elif min_seasons_filter > 1:
                seasons_per_owner = season_rosters.groupby("owner")["season"].nunique()
                keep = seasons_per_owner[seasons_per_owner >= min_seasons_filter].index
                summary = summary[summary["owner"].isin(keep)].reset_index(drop=True)
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

    with tab4:
        st.subheader("🎯 Lineup Decision Quality")
        st.caption("Missed points = optimal possible score minus actual starter score. Grade: A <5pts missed, B 5–15, C 15–30, D >30.")

        dq = lineup_decision_quality(season_rosters, selected_season, league_id)
        if dq.empty:
            st.info("No decision quality data available.")
        else:
            # Manager summary
            grade_order = ["A", "B", "C", "D"]
            summary = dq.groupby("owner").agg(
                avg_missed=("missed_points", "mean"),
                total_missed=("missed_points", "sum"),
                worst_week=("missed_points", "max"),
                weeks=("missed_points", "count"),
            ).reset_index()
            summary["avg_missed"] = summary["avg_missed"].round(2)
            summary["total_missed"] = summary["total_missed"].round(2)
            summary["worst_week"] = summary["worst_week"].round(2)

            grade_counts = dq.groupby(["owner", "decision_grade"]).size().unstack(fill_value=0).reindex(columns=grade_order, fill_value=0)
            grade_counts.columns = [f"Grade {g}" for g in grade_order]
            summary = summary.merge(grade_counts.reset_index(), on="owner", how="left")

            st.dataframe(
                summary.sort_values("avg_missed").rename(columns={
                    "owner": "Manager", "avg_missed": "Avg Missed/Wk",
                    "total_missed": "Total Missed", "worst_week": "Worst Week",
                    "weeks": "Weeks",
                }),
                use_container_width=True, hide_index=True,
            )

            fig = px.bar(
                summary.sort_values("avg_missed", ascending=True),
                x="avg_missed", y="owner", orientation="h",
                labels={"avg_missed": "Avg Pts Missed/Week", "owner": "Manager"},
                color="avg_missed",
                color_continuous_scale="RdYlGn_r",
                title="Average Points Left on Bench (Lower = Better Decisions)",
            )
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

            st.divider()
            st.subheader("Worst Individual Lineup Decisions")
            worst = dq.nlargest(20, "missed_points")[["season", "week", "owner", "actual_score", "optimal_score", "missed_points", "decision_grade"]].rename(columns={
                "season": "Season", "week": "Week", "owner": "Manager",
                "actual_score": "Actual", "optimal_score": "Optimal",
                "missed_points": "Missed", "decision_grade": "Grade",
            })
            worst["Actual"] = worst["Actual"].round(2)
            worst["Optimal"] = worst["Optimal"].round(2)
            worst["Missed"] = worst["Missed"].round(2)
            st.dataframe(worst, use_container_width=True, hide_index=True)
