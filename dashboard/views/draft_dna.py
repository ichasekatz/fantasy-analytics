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
from utils import apply_league_filter, is_defensive_position, style_dataframe


def render(conn) -> None:
    st.title("🧬 Draft DNA")
    st.caption("**VORP** (Value Over Replacement Player) = points scored above what an average player available at that pick slot would have scored. Positive = outperformed expectations; negative = underperformed.")

    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks ORDER BY season, overall").df())
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    lid: str | None = st.session_state.get("selected_league_id")

    if draft_df.empty:
        st.info("No draft data available.")
        return

    # Per-page IDP toggle — filters defensive players from draft data only
    if "position" in draft_df.columns:
        _is_def = draft_df["position"].apply(lambda p: is_defensive_position(str(p)) if pd.notna(p) else False)
        if _is_def.any():
            _exclude_idp_draft = st.checkbox(
                "Exclude defensive players (IDP) from draft analysis",
                value=st.session_state.get("exclude_defensive", True),
                key="dna_exclude_idp",
                help="2019 season had individual defensive players. Exclude for cleaner position/VORP analysis.",
            )
            if _exclude_idp_draft:
                draft_df = draft_df[~_is_def]
                if "position" in rosters_df.columns:
                    rosters_df = rosters_df[~rosters_df["position"].apply(
                        lambda p: is_defensive_position(str(p)) if pd.notna(p) else False
                    )]

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
            )
            if not pos_pivot.empty:
                _heat = go.Figure(data=go.Heatmap(
                    z=pos_pivot.values,
                    x=list(pos_pivot.columns),
                    y=list(pos_pivot.index),
                    colorscale="YlOrRd",
                    text=pos_pivot.values,
                    texttemplate="%{text:.1f}",
                    showscale=True,
                    hovertemplate="Manager: %{y}<br>Position: %{x}<br>Avg picks: %{z:.1f}<extra></extra>",
                ))
                _heat.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=max(350, len(pos_pivot) * 32 + 80),
                    xaxis_title="Position", yaxis_title="Manager",
                    yaxis={"autorange": "reversed"},
                )
                st.plotly_chart(_heat, use_container_width=True)
            else:
                st.info("No data.")
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
                )
                if not rnd_pivot.empty:
                    _rnd_heat = go.Figure(data=go.Heatmap(
                        z=rnd_pivot.values,
                        x=list(rnd_pivot.columns),
                        y=list(rnd_pivot.index),
                        colorscale="YlOrRd",
                        text=rnd_pivot.values,
                        texttemplate="%{text}",
                        showscale=True,
                        hovertemplate="Manager: %{y}<br>Position: %{x}<br>Picks: %{z}<extra></extra>",
                    ))
                    _rnd_heat.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        height=max(350, len(rnd_pivot) * 32 + 80),
                        xaxis_title="Position", yaxis_title="Manager",
                        yaxis={"autorange": "reversed"},
                    )
                    st.plotly_chart(_rnd_heat, use_container_width=True)
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
        min_seasons_filter = st.session_state.get("min_seasons_played", 1)
        if min_seasons_filter > 1 and "Drafts" in career.columns:
            career = career[career["Drafts"] >= min_seasons_filter]
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
        vorp_hib = [c for c in display.columns if "VORP" in c or "Steals" in c]
        vorp_lib = [c for c in display.columns if "Busts" in c]
        st.dataframe(style_dataframe(display, higher_is_better=vorp_hib, lower_is_better=vorp_lib), use_container_width=True, hide_index=True)
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
        st.dataframe(style_dataframe(display,
            higher_is_better=["Total VORP", "Avg VORP/Pick", "Steals", "Non-Keeper VORP"],
            lower_is_better=["Busts"]), use_container_width=True, hide_index=True)
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
    import numpy as np

    st.subheader("Pick Value Map")
    st.caption("Actual VORP delivered vs. pick slot. Dots above the trend line = value picks. Below = busts.")

    _map_rounds = sorted(draft_df["round"].dropna().unique().astype(int)) if "round" in draft_df.columns else []
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        sel_season = st.selectbox(
            "Season",
            ["All Time"] + [str(s) for s in seasons],
            key="dna_map_season",
            index=0,
        )
    with col_b:
        owners = sorted(draft_df["owner_name"].dropna().unique())
        sel_owner = st.selectbox("Manager", ["All Managers"] + list(owners), key="dna_map_owner")
    with col_c:
        sel_map_rd = st.selectbox("Round", ["All Rounds"] + [f"Round {r}" for r in _map_rounds], key="dna_map_rd")

    # Build dpv
    if sel_season == "All Time":
        all_dpv = []
        for s in seasons:
            _dpv = draft_pick_value(draft_df, rosters_df, season=int(s), league_id=lid)
            if not _dpv.empty:
                _dpv = _dpv.copy()
                _dpv["season"] = int(s)
                all_dpv.append(_dpv)
        if not all_dpv:
            st.info("No pick value data.")
            return
        dpv = pd.concat(all_dpv, ignore_index=True)
    else:
        dpv = draft_pick_value(draft_df, rosters_df, season=int(sel_season), league_id=lid)
        if not dpv.empty:
            dpv = dpv.copy()
            dpv["season"] = int(sel_season)

    if dpv.empty:
        st.info("No pick value data for this selection.")
        return

    dpv = dpv.dropna(subset=["vorp"])

    if sel_owner != "All Managers":
        dpv = dpv[dpv["owner_name"] == sel_owner]

    if sel_map_rd != "All Rounds" and "round" in dpv.columns:
        dpv = dpv[dpv["round"] == int(sel_map_rd.split()[-1])]

    if dpv.empty:
        st.info("No picks found for this selection.")
        return

    # Gradient scatter: color by VORP value
    vmin = float(dpv["vorp"].min())
    vmax = float(dpv["vorp"].max())
    hover_text = dpv["player"] + " (" + dpv["position"].fillna("?") + ")" + (
        " — " + dpv["season"].astype(str) if sel_season == "All Time" else ""
    ) + "<br>Owner: " + dpv["owner_name"].fillna("?")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dpv["overall"],
        y=dpv["vorp"],
        mode="markers",
        marker=dict(
            color=dpv["vorp"],
            colorscale=[[0.0, "#E53E3E"], [0.5, "#F7C59F"], [1.0, "#38A169"]],
            cmin=vmin,
            cmax=vmax,
            size=9,
            opacity=0.85,
            colorbar=dict(title="VORP", thickness=12),
        ),
        text=hover_text,
        hovertemplate="%{text}<br>Pick #%{x}<br>VORP: %{y:.1f}<extra></extra>",
        showlegend=False,
    ))

    # Trend line
    if len(dpv) > 2:
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
    all_time = sel_season == "All Time"
    cols_show = [c for c in (["season"] if all_time else []) + ["overall", "round", "owner_name", "player", "position", "vorp", "label"] if c in dpv.columns]
    display = dpv[cols_show].rename(columns={
        "season": "Season", "overall": "Pick", "round": "Rd", "owner_name": "Owner",
        "player": "Player", "position": "Pos",
        "vorp": "VORP", "label": "Label",
    })
    if "VORP" in display.columns:
        display["VORP"] = display["VORP"].round(1)
    st.dataframe(style_dataframe(display, higher_is_better=["VORP"]), use_container_width=True, hide_index=True)


def _render_best_picks(draft_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Best Draft Picks in League History")
    st.caption("Top picks by VORP — the most valuable selections relative to replacement level.")

    _seasons = sorted(draft_df["season"].dropna().unique())
    _rounds = sorted(draft_df["round"].dropna().unique().astype(int)) if "round" in draft_df.columns else []
    col1, col2, col3 = st.columns(3)
    with col1:
        top_n = st.selectbox("Show top", [25, 50, 100], key="best_picks_n")
    with col2:
        sel_yr = st.selectbox("Season", ["All Time"] + [str(s) for s in _seasons], key="best_picks_yr")
    with col3:
        sel_rd = st.selectbox("Round", ["All Rounds"] + [f"Round {r}" for r in _rounds], key="best_picks_rd")
    _df = draft_df if sel_yr == "All Time" else draft_df[draft_df["season"] == int(sel_yr)]
    if sel_rd != "All Rounds":
        _rnd = int(sel_rd.split()[-1])
        _df = _df[_df["round"] == _rnd]
    _rdf = rosters_df if sel_yr == "All Time" else rosters_df[rosters_df["season"] == int(sel_yr)] if "season" in rosters_df.columns else rosters_df
    best = best_picks_ever(_df, _rdf, league_id=lid, top_n=top_n)

    if best.empty:
        st.info("No data.")
        return

    cols = [c for c in ["rank", "season", "overall", "round", "owner_name", "player", "position", "vorp", "total_points"] if c in best.columns]
    display = best[cols].rename(columns={
        "rank": "#", "season": "Season", "overall": "Pick", "round": "Rd",
        "owner_name": "Owner", "player": "Player", "position": "Pos",
        "vorp": "VORP", "total_points": "Total Pts",
    })
    for col in ["VORP", "Total Pts"]:
        if col in display.columns:
            display[col] = display[col].round(1)
    st.dataframe(style_dataframe(display, higher_is_better=["VORP", "Total Pts"]), use_container_width=True, hide_index=True)


def _render_worst_picks(draft_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Worst Draft Picks in League History")
    st.caption("Top busts by VORP — the most disappointing selections. Keepers excluded.")

    _seasons = sorted(draft_df["season"].dropna().unique())
    _rounds = sorted(draft_df["round"].dropna().unique().astype(int)) if "round" in draft_df.columns else []
    col1, col2, col3 = st.columns(3)
    with col1:
        top_n = st.selectbox("Show top", [25, 50, 100], key="worst_picks_n")
    with col2:
        sel_yr = st.selectbox("Season", ["All Time"] + [str(s) for s in _seasons], key="worst_picks_yr")
    with col3:
        sel_rd = st.selectbox("Round", ["All Rounds"] + [f"Round {r}" for r in _rounds], key="worst_picks_rd")
    _df = draft_df if sel_yr == "All Time" else draft_df[draft_df["season"] == int(sel_yr)]
    if sel_rd != "All Rounds":
        _rnd = int(sel_rd.split()[-1])
        _df = _df[_df["round"] == _rnd]
    _rdf = rosters_df if sel_yr == "All Time" else rosters_df[rosters_df["season"] == int(sel_yr)] if "season" in rosters_df.columns else rosters_df
    worst = worst_picks_ever(_df, _rdf, league_id=lid, top_n=top_n)

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
    st.dataframe(style_dataframe(display, lower_is_better=["VORP", "Total Pts"]), use_container_width=True, hide_index=True)
