"""Draft DNA: draft tendencies, position preferences, steals, busts, and pick history."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.draft_analytics import (
    best_picks_ever,
    draft_pick_value,
    manager_draft_grades,
    vorp,
    worst_picks_ever,
)
from utils import apply_league_filter


def render(conn) -> None:
    st.title("🧬 Draft DNA")

    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks ORDER BY season, overall").df())
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    lid: str | None = st.session_state.get("selected_league_id")

    if draft_df.empty:
        st.info("No draft data available.")
        return

    seasons = sorted(draft_df["season"].unique())

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Position Tendencies",
        "Manager Draft Grades",
        "Pick Value Map",
        "🏆 Best Picks Ever",
        "💀 Worst Picks Ever",
    ])

    with tab1:
        _render_position_tendencies(draft_df)

    with tab2:
        _render_draft_grades(draft_df, rosters_df, lid, seasons)

    with tab3:
        _render_pick_value_map(draft_df, rosters_df, lid, seasons)

    with tab4:
        _render_best_picks(draft_df, rosters_df, lid)

    with tab5:
        _render_worst_picks(draft_df, rosters_df, lid)


def _render_position_tendencies(draft_df: pd.DataFrame) -> None:
    st.subheader("Draft Position Tendencies by Manager")
    st.caption("Which positions each manager prioritizes — early, mid, and late draft.")

    if "position" not in draft_df.columns:
        st.info("Position data unavailable.")
        return

    # Early = rounds 1-4, mid = 5-8, late = 9+
    draft_df = draft_df.copy()
    draft_df["tier"] = pd.cut(
        draft_df["round"],
        bins=[0, 4, 8, 99],
        labels=["Early (1-4)", "Mid (5-8)", "Late (9+)"],
    )

    owners = sorted(draft_df["owner_name"].dropna().unique())
    sel_owner = st.selectbox("Manager", ["All Managers"] + list(owners), key="dna_owner")

    if sel_owner != "All Managers":
        view = draft_df[draft_df["owner_name"] == sel_owner]
    else:
        view = draft_df

    pos_counts = (
        view.groupby(["position", "tier"], observed=True)
        .size()
        .reset_index(name="picks")
    )

    if pos_counts.empty:
        st.info("No data.")
        return

    fig = px.bar(
        pos_counts,
        x="position",
        y="picks",
        color="tier",
        barmode="group",
        labels={"position": "Position", "picks": "Picks", "tier": "Draft Tier"},
        color_discrete_map={
            "Early (1-4)": "#FF6B35",
            "Mid (5-8)": "#F7C59F",
            "Late (9+)": "#4A5568",
        },
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    if sel_owner == "All Managers":
        st.subheader("Round 1 Position Distribution by Manager")
        r1 = draft_df[draft_df["round"] == 1].copy()
        if not r1.empty:
            r1_pivot = (
                r1.groupby(["owner_name", "position"])
                .size()
                .reset_index(name="picks")
                .pivot(index="owner_name", columns="position", values="picks")
                .fillna(0)
                .reset_index()
            )
            st.dataframe(r1_pivot, use_container_width=True, hide_index=True)


def _render_draft_grades(
    draft_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    lid: str | None,
    seasons: list,
) -> None:
    st.subheader("Manager Draft Grades by Season")

    sel_season = st.selectbox(
        "Season",
        ["All Seasons"] + [str(s) for s in seasons],
        key="dna_grade_season",
    )

    s = None if sel_season == "All Seasons" else int(sel_season)
    grades = manager_draft_grades(draft_df, rosters_df, season=s, league_id=lid)

    if grades.empty:
        st.info("No grade data available.")
        return

    display = grades.rename(columns={
        "owner_name": "Manager",
        "season": "Season",
        "total_draft_vorp": "Total VORP",
        "avg_pick_vorp": "Avg VORP/Pick",
        "steals_count": "Steals",
        "busts_count": "Busts",
        "keeper_count": "Keepers",
        "non_keeper_vorp": "Non-Keeper VORP",
        "draft_rank": "Rank",
    })
    for col in ["Total VORP", "Avg VORP/Pick", "Non-Keeper VORP"]:
        if col in display.columns:
            display[col] = display[col].round(1)

    st.dataframe(display, use_container_width=True, hide_index=True)

    if "Total VORP" in display.columns and not grades.empty:
        fig = px.bar(
            display.sort_values("Total VORP", ascending=True),
            x="Total VORP",
            y="Manager",
            orientation="h",
            color="Total VORP",
            color_continuous_scale=["#E53E3E", "#F7C59F", "#38A169"],
            labels={"Total VORP": "Draft VORP"},
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)


def _render_pick_value_map(
    draft_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    lid: str | None,
    seasons: list,
) -> None:
    st.subheader("Pick Value Map")
    st.caption("Actual VORP delivered vs. pick slot. Dots above the trend line = value picks. Below = busts.")

    sel_season = st.selectbox(
        "Season",
        [str(s) for s in seasons],
        key="dna_map_season",
        index=len(seasons) - 1,
    )

    dpv = draft_pick_value(draft_df, rosters_df, season=int(sel_season), league_id=lid)

    if dpv.empty:
        st.info("No pick value data for this season.")
        return

    dpv = dpv.dropna(subset=["vorp"])
    dpv["color"] = dpv["label"].map({"steal": "#38A169", "bust": "#E53E3E", "fair": "#718096", "unknown": "#4A5568"})
    dpv["label_display"] = dpv["label"].str.title()

    fig = go.Figure()

    for label_val, color in [("Steal", "#38A169"), ("Fair", "#718096"), ("Bust", "#E53E3E"), ("Unknown", "#4A5568")]:
        subset = dpv[dpv["label_display"] == label_val]
        if not subset.empty:
            fig.add_trace(go.Scatter(
                x=subset["overall"],
                y=subset["vorp"],
                mode="markers",
                name=label_val,
                marker=dict(color=color, size=10, opacity=0.8),
                text=subset["player"] + " (" + subset["position"] + ")",
                hovertemplate="%{text}<br>Pick #%{x}<br>VORP: %{y:.1f}<extra></extra>",
            ))

    # Trend line
    if len(dpv) > 2:
        import numpy as np
        z = np.polyfit(dpv["overall"].fillna(0), dpv["vorp"].fillna(0), 2)
        p = np.poly1d(z)
        x_range = range(int(dpv["overall"].min()), int(dpv["overall"].max()) + 1)
        fig.add_trace(go.Scatter(
            x=list(x_range),
            y=[p(x) for x in x_range],
            mode="lines",
            name="Expected",
            line=dict(color="#A0AEC0", dash="dash", width=1),
            hoverinfo="skip",
        ))

    fig.update_layout(
        xaxis_title="Overall Pick",
        yaxis_title="VORP",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Pick Detail")
    cols_show = [c for c in ["overall", "round", "owner_name", "player", "position", "keeper", "vorp", "label"] if c in dpv.columns]
    display = dpv[cols_show].rename(columns={
        "overall": "Pick", "round": "Rd", "owner_name": "Owner",
        "player": "Player", "position": "Pos", "keeper": "K",
        "vorp": "VORP", "label": "Label",
    })
    if "VORP" in display.columns:
        display["VORP"] = display["VORP"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_best_picks(draft_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Best Draft Picks in League History")
    st.caption("Top 25 picks by VORP — the most valuable selections relative to replacement level.")

    best = best_picks_ever(draft_df, rosters_df, league_id=lid)

    if best.empty:
        st.info("No data.")
        return

    cols = [c for c in ["rank", "season", "overall", "round", "owner_name", "player", "position", "keeper", "vorp", "total_points"] if c in best.columns]
    display = best[cols].rename(columns={
        "rank": "#", "season": "Season", "overall": "Pick", "round": "Rd",
        "owner_name": "Owner", "player": "Player", "position": "Pos",
        "keeper": "Keeper", "vorp": "VORP", "total_points": "Total Pts",
    })
    for col in ["VORP", "Total Pts"]:
        if col in display.columns:
            display[col] = display[col].round(1)

    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_worst_picks(draft_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Worst Draft Picks in League History")
    st.caption("Top 25 busts by VORP — the most disappointing selections. Keepers excluded.")

    worst = worst_picks_ever(draft_df, rosters_df, league_id=lid)

    if worst.empty:
        st.info("No data.")
        return

    cols = [c for c in ["rank", "season", "overall", "round", "owner_name", "player", "position", "vorp", "total_points"] if c in worst.columns]
    display = worst[cols].rename(columns={
        "rank": "#", "season": "Season", "overall": "Pick", "round": "Rd",
        "owner_name": "Owner", "player": "Player", "position": "Pos",
        "vorp": "VORP", "total_points": "Total Pts",
    })
    for col in ["VORP", "Total Pts"]:
        if col in display.columns:
            display[col] = display[col].round(1)

    st.dataframe(display, use_container_width=True, hide_index=True)
