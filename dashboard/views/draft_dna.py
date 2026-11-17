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
    st.caption("**VORP** (Value Over Replacement Player) = points scored above what an average player available at that pick slot would have scored. Positive = outperformed expectations; negative = underperformed.")

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
        max_round = int(draft_df["round"].max()) if not draft_df.empty else 15
        round_opts = ["Average (all rounds)"] + [f"Round {r}" for r in range(1, max_round + 1)]
        sel_round = st.selectbox("Round View", round_opts, key="dna_round_sel")

        if sel_round == "Average (all rounds)":
            st.subheader("Position Distribution by Manager (Avg per Draft)")
            # Average picks per position per manager across all seasons
            pos_pivot = (
                draft_df.groupby(["owner_name", "season", "position"])
                .size()
                .reset_index(name="picks")
                .groupby(["owner_name", "position"])["picks"]
                .mean()
                .reset_index(name="avg_picks")
                .pivot(index="owner_name", columns="position", values="avg_picks")
                .fillna(0)
                .round(1)
                .reset_index()
            )
            st.dataframe(pos_pivot, use_container_width=True, hide_index=True)
        else:
            rnd = int(sel_round.split()[-1])
            st.subheader(f"Round {rnd} Position Distribution by Manager")
            rnd_df = draft_df[draft_df["round"] == rnd].copy()
            if not rnd_df.empty:
                rnd_pivot = (
                    rnd_df.groupby(["owner_name", "position"])
                    .size()
                    .reset_index(name="picks")
                    .pivot(index="owner_name", columns="position", values="picks")
                    .fillna(0)
                    .astype(int)
                    .reset_index()
                )
                st.dataframe(rnd_pivot, use_container_width=True, hide_index=True)
            else:
                st.info(f"No picks found in round {rnd}.")


def _render_draft_grades(
    draft_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    lid: str | None,
    seasons: list,
) -> None:
    st.subheader("Manager Draft Grades by Season")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        sel_season = st.selectbox(
            "Season",
            ["All Seasons"] + [str(s) for s in seasons],
            key="dna_grade_season",
        )
    with col_b:
        avg_mode = False
        if sel_season == "All Seasons":
            avg_mode = st.checkbox("Career averages", value=True, key="dna_grade_avg",
                                   help="Collapse to one row per manager, averaged across all drafts.")

    s = None if sel_season == "All Seasons" else int(sel_season)
    grades = manager_draft_grades(draft_df, rosters_df, season=s, league_id=lid)

    if grades.empty:
        st.info("No grade data available.")
        return

    if avg_mode and sel_season == "All Seasons":
        # Aggregate to one row per manager
        agg_cols = {c: "mean" for c in ["total_draft_vorp", "avg_pick_vorp", "steals_count",
                                         "busts_count", "keeper_count", "non_keeper_vorp"] if c in grades.columns}
        agg_cols["season"] = "count"
        career = grades.groupby("owner_name").agg(agg_cols).reset_index()
        career = career.rename(columns={"season": "Drafts"})
        career = career.sort_values("avg_pick_vorp", ascending=False).reset_index(drop=True)
        career.insert(0, "Rank", range(1, len(career) + 1))
        display = career.rename(columns={
            "owner_name": "Manager",
            "total_draft_vorp": "Avg Total VORP",
            "avg_pick_vorp": "Avg VORP/Pick",
            "steals_count": "Avg Steals",
            "busts_count": "Avg Busts",
            "keeper_count": "Avg Keepers",
            "non_keeper_vorp": "Avg Non-Keeper VORP",
        })
        for col in [c for c in display.columns if "VORP" in c or "Steals" in c or "Busts" in c]:
            if col in display.columns:
                display[col] = display[col].round(1)
        st.dataframe(display, use_container_width=True, hide_index=True)
        chart_col = "Avg VORP/Pick"
        chart_label = "Avg VORP/Pick"
    else:
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
        chart_col = "Total VORP"
        chart_label = "Draft VORP"

    if chart_col in display.columns:
        fig = px.bar(
            display.sort_values(chart_col, ascending=True),
            x=chart_col,
            y="Manager",
            orientation="h",
            color=chart_col,
            color_continuous_scale=["#E53E3E", "#F7C59F", "#38A169"],
            labels={chart_col: chart_label},
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
    dpv["label"] = dpv["label"].fillna("unknown")
    dpv["color"] = dpv["label"].map({"steal": "#38A169", "bust": "#E53E3E", "fair": "#718096", "unknown": "#A0AEC0"})
    dpv["label_display"] = dpv["label"].str.title()

    fig = go.Figure()

    for label_val, color in [("Steal", "#38A169"), ("Fair", "#718096"), ("Bust", "#E53E3E"), ("Unknown", "#A0AEC0")]:
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
