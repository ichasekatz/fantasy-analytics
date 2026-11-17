"""Draft board page: picks by season, keeper flags, picks-per-team summary."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))

from utils import apply_league_filter


def _pick_quality(draft_df: pd.DataFrame, rosters_df: pd.DataFrame) -> pd.DataFrame:
    """Compute pick quality score based on team contribution vs expected.

    For each drafted player, computes what % of their team's total starter
    points they contributed (actual contribution). Then compares to the
    average contribution of all picks at that round number across all teams.

    Returns draft_df with added columns:
      - actual_pts: player's total starter points that season
      - team_total_pts: drafter's team total starter points that season
      - contribution_pct: actual_pts / team_total_pts
      - expected_pct: average contribution_pct for picks in the same round
      - quality_delta: contribution_pct - expected_pct (positive = outperformed)
      - quality_norm: quality_delta normalized to [-1, 1] for coloring
    """
    if rosters_df.empty or draft_df.empty:
        return draft_df.assign(quality_norm=0.0)

    starters = rosters_df[rosters_df["starter"].fillna(False)].copy()
    starters["points"] = pd.to_numeric(starters["points"], errors="coerce").fillna(0)

    player_pts = (
        starters.groupby(["season", "owner_name", "player"])["points"]
        .sum()
        .reset_index(name="actual_pts")
    )
    team_pts = (
        starters.groupby(["season", "owner_name"])["points"]
        .sum()
        .reset_index(name="team_total_pts")
    )

    df = draft_df.copy()
    df = df.merge(
        player_pts.rename(columns={"owner_name": "owner_name_r"}),
        left_on=["season", "owner_name", "player"],
        right_on=["season", "owner_name_r", "player"],
        how="left",
    ).drop(columns=["owner_name_r"], errors="ignore")
    df = df.merge(
        team_pts.rename(columns={"owner_name": "owner_name_r"}),
        left_on=["season", "owner_name"],
        right_on=["season", "owner_name_r"],
        how="left",
    ).drop(columns=["owner_name_r"], errors="ignore")

    df["actual_pts"] = df["actual_pts"].fillna(0)
    df["team_total_pts"] = df["team_total_pts"].fillna(0)
    df["contribution_pct"] = df.apply(
        lambda r: r["actual_pts"] / r["team_total_pts"] if r["team_total_pts"] > 0 else 0.0,
        axis=1,
    )

    expected = df.groupby("round")["contribution_pct"].mean().rename("expected_pct")
    df = df.merge(expected, on="round", how="left")
    df["quality_delta"] = df["contribution_pct"] - df["expected_pct"]

    # Normalize: clamp to 2*std range then map to [-1, 1]
    std = df["quality_delta"].std()
    if std and std > 0:
        df["quality_norm"] = (df["quality_delta"] / (2 * std)).clip(-1, 1)
    else:
        df["quality_norm"] = 0.0

    return df


def _color_quality(val: float) -> str:
    """Map quality_norm in [-1, 1] to a background color (red → yellow → green)."""
    if pd.isna(val):
        return ""
    # Clamp
    v = max(-1.0, min(1.0, float(val)))
    if v >= 0:
        # 0 → yellow (#ffd700), 1 → green (#22c55e)
        r = int(255 * (1 - v) + 34 * v)
        g = int(215 * (1 - v) + 197 * v)
        b = int(0 * (1 - v) + 94 * v)
    else:
        # -1 → red (#ef4444), 0 → yellow (#ffd700)
        r = int(239 + (255 - 239) * (v + 1))
        g = int(68 + (215 - 68) * (v + 1))
        b = int(68 + (0 - 68) * (v + 1))
    return f"background-color: rgb({r},{g},{b}); color: #000"


def render(conn) -> None:
    st.title("🎯 Draft Board")

    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks ORDER BY season, overall").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    rosters_df = apply_league_filter(conn.execute("SELECT season, owner_name, player, points, starter FROM rosters").df())

    seasons = sorted(draft_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels)
    selected_season = seasons[season_labels.index(selected_label)]

    season_draft = draft_df[draft_df["season"] == selected_season].copy()
    season_rosters = rosters_df[rosters_df["season"] == selected_season].copy()

    if season_draft.empty:
        st.info("No draft data available for this season.")
        return

    num_rounds = int(season_draft["round"].max())
    num_teams = len(season_draft["team_id"].unique())
    num_keepers = int(season_draft["keeper"].sum())
    st.caption(f"{num_rounds} rounds · {num_teams} teams · {num_keepers} keeper(s)")

    show_quality = st.toggle("Show pick quality colors (team contribution vs expected)", value=False, key="draft_quality")

    tab1, tab2 = st.tabs(["Draft Board", "By Manager"])

    if show_quality and not season_rosters.empty:
        season_draft = _pick_quality(season_draft, season_rosters)
    elif show_quality:
        season_draft["quality_norm"] = 0.0

    with tab1:
        display = season_draft[["overall", "round", "owner_name", "team_name", "player", "position", "keeper", "cost"]].rename(columns={
            "overall": "Pick", "round": "Rd", "owner_name": "Owner",
            "team_name": "Team", "player": "Player", "position": "Pos",
            "keeper": "Keeper", "cost": "Cost",
        }).copy()

        if show_quality and "quality_norm" in season_draft.columns:
            display["Quality"] = season_draft["quality_norm"].values
            display["Pts"] = season_draft["actual_pts"].round(1).values if "actual_pts" in season_draft.columns else 0

            def _style_row(row):
                q = row.get("Quality", float("nan"))
                color = _color_quality(q) if pd.notna(q) else ""
                return [color if col in ("Player", "Quality", "Pts") else "" for col in row.index]

            styled = display.style.apply(_style_row, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.caption("🟢 Green = outperformed round expectation · 🔴 Red = underperformed · based on starter points as % of team total")
        else:
            st.dataframe(display, use_container_width=True, hide_index=True)

    with tab2:
        managers = sorted(season_draft["owner_name"].dropna().unique())
        selected_mgr = st.selectbox("Manager", managers)
        mgr_picks = season_draft[season_draft["owner_name"] == selected_mgr].copy()

        st.write(f"**{len(mgr_picks)} picks** · **{int(mgr_picks['keeper'].sum())} keepers**")
        display_mgr_cols = ["overall", "round", "player", "position", "keeper", "cost"]
        display_mgr = mgr_picks[[c for c in display_mgr_cols if c in mgr_picks.columns]].rename(columns={
            "overall": "Pick", "round": "Rd", "player": "Player",
            "position": "Pos", "keeper": "Keeper", "cost": "Cost",
        }).copy()

        if show_quality and "quality_norm" in mgr_picks.columns:
            display_mgr["Quality"] = mgr_picks["quality_norm"].values
            display_mgr["Pts"] = mgr_picks["actual_pts"].round(1).values if "actual_pts" in mgr_picks.columns else 0

            def _style_mgr_row(row):
                q = row.get("Quality", float("nan"))
                color = _color_quality(q) if pd.notna(q) else ""
                return [color if col in ("Player", "Quality", "Pts") else "" for col in row.index]

            styled_mgr = display_mgr.style.apply(_style_mgr_row, axis=1)
            st.dataframe(styled_mgr, use_container_width=True, hide_index=True)
        else:
            st.dataframe(display_mgr, use_container_width=True, hide_index=True)

        pos_counts = mgr_picks["position"].value_counts().reset_index()
        pos_counts.columns = ["Position", "Count"]
        st.subheader("Positional Breakdown")
        st.dataframe(pos_counts, use_container_width=True, hide_index=True)
