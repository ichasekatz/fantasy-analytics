"""Luck analysis page: schedule strength, weekly scoring luck, expected wins."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.luck import luck_metrics, schedule_luck
from utils import apply_league_filter


_EXTRA_COLS = ["opp_avg_pf", "opp_season_avg_pf", "opp_above_avg", "opp_win_pct"]


def _all_seasons_schedule_luck(matchups_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    seasons = sorted(matchups_df["season"].dropna().unique())
    frames = []
    for s in seasons:
        ldf = schedule_luck(matchups_df, int(s))
        if not ldf.empty:
            ldf["season"] = s
            frames.append(ldf)
    if not frames:
        return pd.DataFrame(), pd.Series(dtype=int)
    combined = pd.concat(frames, ignore_index=True)
    seasons_played = combined.groupby("owner")["season"].nunique()
    agg_map = {
        "actual_wins": "sum",
        "expected_wins": "sum",
        "schedule_difficulty": "mean",
        "opp_avg_pf": "mean",
        "opp_season_avg_pf": "mean",
        "opp_above_avg": "mean",
        "opp_win_pct": "mean",
    }
    valid_agg = {k: v for k, v in agg_map.items() if k in combined.columns}
    agg = combined.groupby("owner").agg(**{k: (k, v) for k, v in valid_agg.items()}).reset_index()
    agg["luck_delta"] = agg["actual_wins"] - agg["expected_wins"]
    return agg.sort_values("opp_above_avg", ascending=False).reset_index(drop=True), seasons_played


def render(conn) -> None:
    st.title("🍀 Luck Analysis")
    st.caption(
        "Who had the toughest schedule? Did your opponents consistently play above their usual level against you? "
        "Luck Δ = actual wins − expected wins (all-play)."
    )

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = ["All Seasons"] + [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(season_labels) - 1)
    all_seasons = selected_label == "All Seasons"

    if all_seasons:
        luck, seasons_played = _all_seasons_schedule_luck(matchups_df)
        min_seasons_filter = st.session_state.get("min_seasons_played", 1)
        if min_seasons_filter > 1 and not luck.empty:
            keep = seasons_played[seasons_played >= min_seasons_filter].index
            luck = luck[luck["owner"].isin(keep)].reset_index(drop=True)
    else:
        selected_season = seasons[season_labels.index(selected_label) - 1]
        luck = schedule_luck(matchups_df, selected_season)

    if luck.empty:
        st.info("No luck data available.")
        return

    has_schedule = all(c in luck.columns for c in _EXTRA_COLS)

    tab_labels = ["Schedule Strength", "Weekly Scoring Luck", "Expected Wins"]
    tabs = st.tabs(tab_labels)

    # ── Tab 1: Schedule Strength ──────────────────────────────────────────────
    with tabs[0]:
        st.caption(
            "**Opp Season Avg PF** = how well your opponents scored across all their games (opponent quality). "
            "**Opp Avg PF vs You** = how much they scored specifically against you. "
            "**Opp Win%** = average record of opponents you faced."
        )

        if has_schedule:
            # Sort by opp_season_avg_pf = hardest schedule
            sched_df = luck.sort_values("opp_season_avg_pf", ascending=False).copy()

            fig = px.bar(
                sched_df,
                x="opp_season_avg_pf", y="owner", orientation="h",
                labels={"opp_season_avg_pf": "Opponent Season Avg PF", "owner": "Manager"},
                color="opp_season_avg_pf",
                color_continuous_scale=["#38A169", "#F7C59F", "#E53E3E"],
                title="Schedule Difficulty — Opponent Scoring Quality",
            )
            fig.update_layout(
                showlegend=False, coloraxis_showscale=False,
                height=max(350, len(luck) * 32),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                yaxis={"categoryorder": "total ascending"},
            )
            st.plotly_chart(fig, use_container_width=True)

            # Opp win% chart
            fig2 = px.bar(
                sched_df.sort_values("opp_win_pct", ascending=False),
                x="opp_win_pct", y="owner", orientation="h",
                labels={"opp_win_pct": "Avg Opponent Win%", "owner": "Manager"},
                color="opp_win_pct",
                color_continuous_scale=["#38A169", "#F7C59F", "#E53E3E"],
                title="Opponent Win% (Record-Based Strength of Schedule)",
            )
            fig2.update_layout(
                showlegend=False, coloraxis_showscale=False,
                height=max(350, len(luck) * 32),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                yaxis={"categoryorder": "total ascending"},
            )
            st.plotly_chart(fig2, use_container_width=True)

            # Detail table
            show_cols = ["owner", "opp_season_avg_pf", "opp_avg_pf", "opp_win_pct"]
            if not all_seasons and "team" in luck.columns:
                show_cols = ["owner", "team"] + show_cols[1:]
            tbl = luck[[c for c in show_cols if c in luck.columns]].copy()
            tbl["opp_season_avg_pf"] = tbl["opp_season_avg_pf"].round(1)
            tbl["opp_avg_pf"] = tbl["opp_avg_pf"].round(1)
            tbl["opp_win_pct"] = tbl["opp_win_pct"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
            tbl = tbl.rename(columns={
                "owner": "Manager", "team": "Team",
                "opp_season_avg_pf": "Opp Season Avg PF",
                "opp_avg_pf": "Opp Avg PF vs You",
                "opp_win_pct": "Opp Win%",
            })
            st.dataframe(tbl.sort_values("Opp Season Avg PF", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("Schedule quality data unavailable for this selection.")

    # ── Tab 2: Weekly Scoring Luck ────────────────────────────────────────────
    with tabs[1]:
        st.caption(
            "**Opp Above Avg** = did your opponents score above/below their own season average when playing you? "
            "Positive = opponents played their best against you (unlucky). "
            "Negative = opponents underperformed against you (lucky)."
        )

        if has_schedule and "opp_above_avg" in luck.columns:
            fig3 = px.bar(
                luck.sort_values("opp_above_avg"),
                x="opp_above_avg", y="owner", orientation="h",
                labels={"opp_above_avg": "Opp Score vs Their Season Avg", "owner": "Manager"},
                color="opp_above_avg",
                color_continuous_scale=["#38A169", "#F7C59F", "#E53E3E"],
                color_continuous_midpoint=0,
                title="Weekly Scoring Luck — Did Opponents Play Above Their Usual Level vs You?",
            )
            fig3.update_layout(
                showlegend=False, coloraxis_showscale=False,
                height=max(350, len(luck) * 32),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                yaxis={"categoryorder": "total ascending"},
            )
            st.plotly_chart(fig3, use_container_width=True)

            show_cols2 = ["owner", "opp_above_avg", "opp_avg_pf", "opp_season_avg_pf"]
            if not all_seasons and "team" in luck.columns:
                show_cols2 = ["owner", "team"] + show_cols2[1:]
            tbl2 = luck[[c for c in show_cols2 if c in luck.columns]].copy()
            tbl2["opp_above_avg"] = tbl2["opp_above_avg"].round(2)
            tbl2["opp_avg_pf"] = tbl2["opp_avg_pf"].round(1)
            tbl2["opp_season_avg_pf"] = tbl2["opp_season_avg_pf"].round(1)
            tbl2 = tbl2.rename(columns={
                "owner": "Manager", "team": "Team",
                "opp_above_avg": "Opp Above Avg",
                "opp_avg_pf": "Opp Avg vs You",
                "opp_season_avg_pf": "Opp Season Avg",
            })
            st.dataframe(tbl2.sort_values("Opp Above Avg", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("Weekly scoring luck data unavailable for this selection.")

    # ── Tab 3: Expected Wins ──────────────────────────────────────────────────
    with tabs[2]:
        st.caption(
            "Expected wins = how many wins a team would expect if they played every other team each week (all-play). "
            "Luck Δ = actual wins − expected wins. Positive = schedule helped you win more than you deserved."
        )

        fig4 = px.bar(
            luck.sort_values("luck_delta"),
            x="luck_delta", y="owner", orientation="h",
            labels={"luck_delta": "Luck Δ (Actual − Expected Wins)", "owner": "Manager"},
            color="luck_delta",
            color_continuous_scale=["#d62728", "#aec7e8", "#1f77b4"],
            color_continuous_midpoint=0,
            title="Luck Delta — Schedule-Adjusted Win Benefit",
        )
        fig4.update_layout(
            showlegend=False, coloraxis_showscale=False,
            height=max(350, len(luck) * 32),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(fig4, use_container_width=True)

        show_cols3 = ["owner", "actual_wins", "expected_wins", "luck_delta"]
        if not all_seasons and "team" in luck.columns:
            show_cols3 = ["owner", "team"] + show_cols3[1:]
        tbl3 = luck[[c for c in show_cols3 if c in luck.columns]].copy()
        tbl3["expected_wins"] = tbl3["expected_wins"].round(2)
        tbl3["luck_delta"] = tbl3["luck_delta"].round(2)
        tbl3 = tbl3.rename(columns={
            "owner": "Manager", "team": "Team",
            "actual_wins": "Actual W", "expected_wins": "Expected W", "luck_delta": "Luck Δ",
        })
        st.dataframe(tbl3.sort_values("Luck Δ", ascending=False), use_container_width=True, hide_index=True)
