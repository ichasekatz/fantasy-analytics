"""Injury & bust impact: starters who went DNP / scored near zero."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from utils import apply_league_filter, is_defensive_position, style_dataframe

_BUST_THRESHOLD = 0.40   # actual / projected < 40% = "bust" (projection mode)
# Extra positions excluded by the LOCAL injury IDP toggle (not the global sidebar toggle)
_INJ_LOCAL_EXCLUDE = {"K", "DST", "DEF", "D_ST", "D/ST"}
_MIN_PROJECTED = 8.0     # ignore low-projection players
_DNP_THRESHOLD = 2.0     # scored ≤ 2 pts as a starter = likely DNP/inactive


def _bust_events(rosters_df: pd.DataFrame) -> pd.DataFrame:
    """Return starter rows where actual << projected OR scored ≤ 2 pts (DNP)."""
    starters = rosters_df[rosters_df["starter"].fillna(False) & rosters_df["points"].notna()].copy()
    has_proj = (
        "projected" in starters.columns
        and starters["projected"].notna().sum() > 0
        and (starters["projected"].fillna(0) > 0).sum() > 0
    )
    if has_proj:
        starters["projected"] = pd.to_numeric(starters["projected"], errors="coerce")
        proj_rows = starters[starters["projected"].fillna(0) >= _MIN_PROJECTED].copy()
        proj_rows["pct_of_proj"] = proj_rows["points"] / proj_rows["projected"].replace(0, float("nan"))
        return proj_rows[proj_rows["pct_of_proj"] < _BUST_THRESHOLD].copy()
    else:
        # No projection data — flag starters who scored ≤ 2 pts (likely DNP/IR)
        dnp = starters[starters["points"] <= _DNP_THRESHOLD].copy()
        dnp["projected"] = float("nan")
        dnp["pct_of_proj"] = float("nan")
        return dnp


def _render_draft_injuries(conn, rosters_df: pd.DataFrame) -> None:
    """Show players drafted healthy who got injured mid-season, ranked by impact."""
    st.subheader("Draft-Day Losses — Players Drafted Healthy, Injured Mid-Season")
    st.caption(
        "Drafted players who produced in early weeks (healthy at draft) but then "
        "disappeared from starting lineups. Excludes already-injured players unless "
        "they recovered then got hurt again."
    )

    lid = st.session_state.get("selected_league_id")
    try:
        draft_df = conn.execute("SELECT * FROM draft_picks").df()
        draft_df = apply_league_filter(draft_df)
    except Exception:
        st.info("No draft pick data available.")
        return

    if draft_df.empty or rosters_df.empty:
        st.info("No data available.")
        return

    rdf = rosters_df.copy()
    rdf["week"] = pd.to_numeric(rdf["week"], errors="coerce")
    rdf["season"] = pd.to_numeric(rdf["season"], errors="coerce")
    rdf["points"] = pd.to_numeric(rdf["points"], errors="coerce").fillna(0)
    rdf = rdf.dropna(subset=["week", "season"])
    rdf["week"] = rdf["week"].astype(int)
    rdf["season"] = rdf["season"].astype(int)

    _EARLY_WEEKS = range(1, 5)   # weeks 1-4 = healthy at draft threshold
    _MIN_EARLY_PTS = 4.0          # must have scored ≥4 pts in at least one early start
    _MISS_WEEKS = 3               # ≥3 consecutive missing weeks after last start = injury
    _REGULAR_SEASON = 13

    rows = []
    for _, pick in draft_df.iterrows():
        player = pick.get("player") or ""
        season = int(pick.get("season", 0))
        owner = pick.get("owner_name") or ""
        rnd = int(pick.get("round", 99))
        if not player or not season or not owner:
            continue

        p_rows = rdf[(rdf["player"] == player) & (rdf["season"] == season) & (rdf["owner_name"] == owner)]
        starter_rows = p_rows[p_rows["starter"].fillna(False).astype(bool)]

        starter_weeks = sorted(starter_rows["week"].tolist())
        if not starter_weeks:
            continue

        # Early starts: weeks 1-4
        early_starts = starter_rows[starter_rows["week"].isin(_EARLY_WEEKS)]
        had_early = len(early_starts) > 0 and early_starts["points"].max() >= _MIN_EARLY_PTS

        last_start = max(starter_weeks)
        missed_after = _REGULAR_SEASON - last_start  # weeks missed after last start

        if had_early and missed_after >= _MISS_WEEKS and last_start < _REGULAR_SEASON - 1:
            # True in-season injury
            # Projected pts lost: sum projected in missed weeks (if available), else use avg
            all_weeks = p_rows["week"].tolist()
            missed_wks = [w for w in range(last_start + 1, _REGULAR_SEASON + 1) if w not in all_weeks]
            proj_col = starter_rows["projected"] if "projected" in starter_rows.columns else None
            avg_proj = float(pd.to_numeric(proj_col, errors="coerce").fillna(0).mean()) if proj_col is not None else 0.0
            pts_before = float(starter_rows[starter_rows["week"] <= last_start]["points"].sum())
            rows.append({
                "Manager": owner,
                "Season": season,
                "Player": player,
                "Round": rnd,
                "Last Start": last_start,
                "Wks Missed": len(missed_wks),
                "Pts Scored": round(pts_before, 1),
                "Avg Proj/Wk": round(avg_proj, 1),
                "Est Pts Lost": round(avg_proj * len(missed_wks), 1),
            })
        elif not had_early and starter_weeks:
            # Possibly already injured at draft but recovered then re-hurt
            # Only include if they had a gap: 0 starts early, starts later, then stops again
            first_start = min(starter_weeks)
            if first_start > 4 and missed_after >= _MISS_WEEKS and last_start < _REGULAR_SEASON - 1:
                p_rows2 = p_rows[p_rows["starter"].fillna(False).astype(bool)]
                pts_scored = float(p_rows2["points"].sum())
                proj_col = p_rows2["projected"] if "projected" in p_rows2.columns else None
                avg_proj = float(pd.to_numeric(proj_col, errors="coerce").fillna(0).mean()) if proj_col is not None else 0.0
                missed_wks = [w for w in range(last_start + 1, _REGULAR_SEASON + 1) if w not in p_rows["week"].tolist()]
                rows.append({
                    "Manager": owner,
                    "Season": season,
                    "Player": player,
                    "Round": rnd,
                    "Last Start": last_start,
                    "Wks Missed": len(missed_wks),
                    "Pts Scored": round(pts_scored, 1),
                    "Avg Proj/Wk": round(avg_proj, 1),
                    "Est Pts Lost": round(avg_proj * len(missed_wks), 1),
                    "Note": "Re-injury (missed early too)",
                })

    if not rows:
        st.info("No in-season injuries detected from draft picks.")
        return

    inj_df = pd.DataFrame(rows).sort_values(["Season", "Est Pts Lost"], ascending=[False, False])

    # Season selector
    seasons_avail = sorted(inj_df["Season"].unique(), reverse=True)
    sel_s = st.selectbox("Season", ["All"] + [str(s) for s in seasons_avail], key="dinj_season")
    if sel_s != "All":
        inj_df = inj_df[inj_df["Season"] == int(sel_s)]

    if inj_df.empty:
        st.info("No injuries for selected season.")
        return

    # Unluckiest manager summary
    mgr_impact = (
        inj_df.groupby("Manager")
        .agg(injuries=("Player", "count"), total_wks_missed=("Wks Missed", "sum"), est_pts_lost=("Est Pts Lost", "sum"))
        .sort_values("est_pts_lost", ascending=False)
        .reset_index()
    )
    fig_inj = px.bar(
        mgr_impact, x="Manager", y="est_pts_lost",
        labels={"est_pts_lost": "Est Pts Lost to Injuries"},
        color="est_pts_lost", color_continuous_scale="Reds",
        title=f"Unluckiest Managers — Estimated Pts Lost to In-Season Injuries ({sel_s})",
    )
    fig_inj.update_coloraxes(showscale=False)
    st.plotly_chart(fig_inj, use_container_width=True)

    st.dataframe(
        inj_df.drop(columns=["Note"], errors="ignore"),
        use_container_width=True, hide_index=True,
    )


def _render_season_injury_impact(busts: pd.DataFrame, rosters_df: pd.DataFrame) -> None:
    """Show estimated points lost to bust/DNP events per manager per season."""
    if busts.empty:
        st.info("No bust events to analyze.")
        return

    rdf = rosters_df.copy()
    for col in ("week", "season", "points"):
        rdf[col] = pd.to_numeric(rdf[col], errors="coerce")
    rdf = rdf.dropna(subset=["week", "season", "points"])
    rdf["week"] = rdf["week"].astype(int)
    rdf["season"] = rdf["season"].astype(int)
    starters = rdf[rdf["starter"].fillna(False).astype(bool)]

    # Build healthy-week avg per (player, season): exclude weeks they scored ≤ _DNP_THRESHOLD
    healthy = starters[starters["points"] > _DNP_THRESHOLD]
    healthy_avg = (
        healthy.groupby(["player", "season"])["points"].mean().reset_index()
        .rename(columns={"points": "healthy_avg"})
    )

    bust_work = busts[["owner_name", "season", "week", "player", "points"]].copy()
    bust_work["season"] = pd.to_numeric(bust_work["season"], errors="coerce").fillna(0).astype(int)
    bust_work["points"] = pd.to_numeric(bust_work["points"], errors="coerce").fillna(0)
    bust_work = bust_work.merge(healthy_avg, on=["player", "season"], how="left")
    bust_work["pts_lost"] = (bust_work["healthy_avg"] - bust_work["points"]).clip(lower=0).fillna(0)

    impact = (
        bust_work.groupby(["owner_name", "season"])
        .agg(bust_events=("player", "count"), est_pts_lost=("pts_lost", "sum"))
        .reset_index()
        .rename(columns={"owner_name": "Manager"})
    )
    impact["est_pts_lost"] = impact["est_pts_lost"].round(1)
    impact = impact.sort_values("est_pts_lost", ascending=False).reset_index(drop=True)

    # Selector: All Seasons vs individual season
    seasons_avail = sorted(impact["season"].unique(), reverse=True)
    sel_s = st.selectbox("Season", ["All Seasons"] + [str(s) for s in seasons_avail], key="simp_season")

    if sel_s == "All Seasons":
        display = (
            impact.groupby("Manager")
            .agg(bust_events=("bust_events", "sum"), est_pts_lost=("est_pts_lost", "sum"))
            .reset_index()
            .sort_values("est_pts_lost", ascending=False)
            .reset_index(drop=True)
        )
        display["est_pts_lost"] = display["est_pts_lost"].round(1)
        title = "Estimated Points Lost to Injuries/Busts — All Seasons"
    else:
        display = impact[impact["season"] == int(sel_s)][["Manager", "bust_events", "est_pts_lost"]].copy()
        title = f"Estimated Points Lost to Injuries/Busts — {sel_s}"

    if display.empty:
        st.info("No data for selected season.")
        return

    fig = px.bar(
        display.sort_values("est_pts_lost", ascending=True),
        x="est_pts_lost", y="Manager", orientation="h",
        color="est_pts_lost",
        color_continuous_scale=["#38A169", "#F7C59F", "#E53E3E"],
        labels={"est_pts_lost": "Est Pts Lost"},
        title=title,
    )
    fig.update_coloraxes(showscale=False)
    fig.update_layout(height=max(300, len(display) * 35))
    st.plotly_chart(fig, use_container_width=True)

    styled = style_dataframe(
        display.rename(columns={"bust_events": "Bust Events", "est_pts_lost": "Est Pts Lost"}),
        lower_is_better=["Est Pts Lost"],
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render(conn) -> None:
    st.title("🩺 Injury Impact")

    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    if rosters_df.empty:
        st.info("No roster data available.")
        return

    has_proj = (
        "projected" in rosters_df.columns
        and rosters_df["projected"].notna().sum() > 0
        and (pd.to_numeric(rosters_df["projected"], errors="coerce").fillna(0) > 0).sum() > 0
    )
    if has_proj:
        st.caption(
            f"Starters projected ≥ {_MIN_PROJECTED} pts who scored < {int(_BUST_THRESHOLD * 100)}% "
            "of projection — likely injured, inactive, or benched by coaching."
        )
    else:
        st.caption(
            f"Starters who scored ≤ {_DNP_THRESHOLD} pts — likely DNP, IR, or inactive. "
            "(No projection data in export; using 0-point threshold instead.)"
        )

    has_idp_positions = "position" in rosters_df.columns and rosters_df["position"].apply(
        lambda p: is_defensive_position(str(p)) if pd.notna(p) else False
    ).any()
    if has_idp_positions:
        exclude_idp_inj = st.checkbox("Exclude defensive players (IDP)", value=False, key="inj_exclude_idp")
        if exclude_idp_inj:
            def _inj_exclude(p: object) -> bool:
                if not pd.notna(p):
                    return False
                tokens = {t.strip() for t in str(p).split(",")}
                return bool(tokens & _INJ_LOCAL_EXCLUDE) or is_defensive_position(str(p))
            rosters_df = rosters_df[~rosters_df["position"].apply(_inj_exclude)]

    busts = _bust_events(rosters_df)

    if busts.empty:
        st.info("No DNP/bust events found.")
        return

    seasons = sorted(rosters_df["season"].dropna().unique(), reverse=True)
    owners = sorted(rosters_df["owner_name"].dropna().unique())

    tab_overview, tab_manager, tab_player, tab_timing, tab_duds = st.tabs([
        "League Overview", "By Manager", "By Player", "Injury Timing", "Duds Leaderboard",
    ])

    # ── Overview ────────────────────────────────────────────────────────────
    with tab_overview:
        season_opts = ["All Seasons"] + [str(s) for s in seasons]
        sel_season_label = st.selectbox("Season", season_opts, key="inj_ov_season")
        if sel_season_label == "All Seasons":
            s_busts = busts.copy()
            season_title = "All Seasons"
        else:
            sel_season = int(sel_season_label)
            s_busts = busts[busts["season"] == sel_season]
            season_title = str(sel_season)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("DNP/bust events", len(s_busts))
        c2.metric("Managers affected", s_busts["owner_name"].nunique())
        c3.metric("Unique players", s_busts["player"].nunique())
        if has_proj and s_busts["projected"].notna().any():
            pts_lost = (s_busts["projected"] - s_busts["points"]).sum()
            c4.metric("Pts lost vs proj", f"{pts_lost:.1f}")
        else:
            c4.metric("Total pts scored (DNP)", f"{s_busts['points'].sum():.1f}")

        st.divider()

        if not s_busts.empty:
            all_ov_owners = sorted(s_busts["owner_name"].dropna().unique())
            sel_ov_owners = st.multiselect("Filter managers", all_ov_owners, default=all_ov_owners, key="inj_ov_mgr")
            s_busts_chart = s_busts[s_busts["owner_name"].isin(sel_ov_owners)]

            if has_proj and s_busts_chart["projected"].notna().any():
                burden = (
                    s_busts_chart.groupby("owner_name")
                    .apply(lambda x: (x["projected"] - x["points"]).sum(), include_groups=False)
                    .reset_index(name="pts_lost")
                    .sort_values("pts_lost", ascending=False)
                    .rename(columns={"owner_name": "Manager"})
                )
                fig = px.bar(
                    burden.sort_values("pts_lost", ascending=True),
                    x="pts_lost", y="Manager", orientation="h",
                    labels={"pts_lost": "Pts Lost vs Projection"},
                    color="pts_lost",
                    color_continuous_scale="Reds",
                    title=f"{season_title} — Projected pts lost to busts/injuries by manager",
                )
            else:
                burden = (
                    s_busts_chart.groupby("owner_name").size()
                    .reset_index(name="dnp_events")
                    .sort_values("dnp_events", ascending=False)
                    .rename(columns={"owner_name": "Manager"})
                )
                fig = px.bar(
                    burden.sort_values("dnp_events", ascending=True),
                    x="dnp_events", y="Manager", orientation="h",
                    labels={"dnp_events": "DNP/Inactive Starters"},
                    color="dnp_events",
                    color_continuous_scale="Reds",
                    title=f"{season_title} — DNP/inactive starter events by manager",
                )
            fig.update_coloraxes(showscale=False)
            fig.update_layout(height=max(350, len(burden) * 35))
            st.plotly_chart(fig, use_container_width=True)

            expander_label = f"All DNP/bust events — {season_title}"
            with st.expander(expander_label):
                disp_cols = ["season", "week", "owner_name", "player", "position", "points"] if sel_season_label == "All Seasons" else ["week", "owner_name", "player", "position", "points"]
                rename_map = {"owner_name": "Manager", "player": "Player", "position": "Pos", "points": "Actual", "season": "Season"}
                if has_proj and "projected" in s_busts.columns:
                    disp_cols += ["projected", "pct_of_proj"]
                    rename_map.update({"projected": "Proj", "pct_of_proj": "% of Proj"})
                display = s_busts[[c for c in disp_cols if c in s_busts.columns]].rename(columns=rename_map).copy()
                if "% of Proj" in display.columns:
                    display["% of Proj"] = (display["% of Proj"] * 100).round(1).astype(str) + "%"
                if "Proj" in display.columns:
                    display["Proj"] = display["Proj"].round(1)
                display["Actual"] = display["Actual"].round(1)
                sort_cols = ["Season", "week", "Manager"] if "Season" in display.columns else ["week", "Manager"]
                sort_cols = [c for c in sort_cols if c in display.columns]
                st.dataframe(display.sort_values(sort_cols) if sort_cols else display,
                             use_container_width=True, hide_index=True)

    # ── By Manager ──────────────────────────────────────────────────────────
    with tab_manager:
        sel_mgr = st.selectbox("Manager", owners, key="inj_mgr")
        mgr_busts = busts[busts["owner_name"] == sel_mgr]

        if mgr_busts.empty:
            st.info("No bust events for this manager.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("DNP/bust events", len(mgr_busts))
            c3.metric("Seasons affected", mgr_busts["season"].nunique())
            if has_proj and mgr_busts["projected"].notna().any():
                total_lost = (mgr_busts["projected"] - mgr_busts["points"]).sum()
                c2.metric("Total pts lost", f"{total_lost:.1f}")
                by_season = (
                    mgr_busts.groupby("season")
                    .apply(lambda x: (x["projected"] - x["points"]).sum(), include_groups=False)
                    .reset_index(name="pts_lost")
                )
                fig = px.bar(by_season, x="season", y="pts_lost",
                             labels={"season": "Season", "pts_lost": "Pts Lost vs Proj"},
                             title=f"{sel_mgr} — Pts lost to busts by season",
                             color_discrete_sequence=["#ef4444"])
            else:
                c2.metric("Total pts scored DNP", f"{mgr_busts['points'].sum():.1f}")
                by_season = mgr_busts.groupby("season").size().reset_index(name="dnp_events")
                fig = px.bar(by_season, x="season", y="dnp_events",
                             labels={"season": "Season", "dnp_events": "DNP events"},
                             title=f"{sel_mgr} — DNP/inactive starters by season",
                             color_discrete_sequence=["#ef4444"])
            st.plotly_chart(fig, use_container_width=True)

            det_cols = ["season", "week", "player", "position", "points"]
            det_rename = {"player": "Player", "position": "Pos", "points": "Actual"}
            if has_proj and "projected" in mgr_busts.columns:
                det_cols += ["projected", "pct_of_proj"]
                det_rename.update({"projected": "Proj", "pct_of_proj": "% of Proj"})
            detail = mgr_busts[[c for c in det_cols if c in mgr_busts.columns]].rename(columns=det_rename).copy()
            if "% of Proj" in detail.columns:
                detail["% of Proj"] = (detail["% of Proj"] * 100).round(1).astype(str) + "%"
            if "Proj" in detail.columns:
                detail["Proj"] = detail["Proj"].round(1)
            detail["Actual"] = detail["Actual"].round(1)
            st.dataframe(detail.sort_values(["season", "week"]),
                         use_container_width=True, hide_index=True)

    # ── By Player ───────────────────────────────────────────────────────────
    with tab_player:
        search = st.text_input("Search player", placeholder="e.g. Davante Adams")
        df = busts.copy()
        if search:
            df = df[df["player"].str.contains(search, case=False, na=False)]

        if df.empty:
            st.info("No bust records found." if search else "Enter a player name to search.")
        else:
            summary = (
                df.groupby("player")
                .agg(
                    bust_weeks=("week", "count"),
                    seasons=("season", "nunique"),
                    pts_lost=("points", lambda x: (df.loc[x.index, "projected"] - x).sum()),
                    managers=("owner_name", lambda x: ", ".join(sorted(x.unique()))),
                )
                .reset_index()
                .rename(columns={
                    "player": "Player", "bust_weeks": "Bust Weeks",
                    "seasons": "Seasons", "pts_lost": "Total Pts Lost", "managers": "Owned By",
                })
                .sort_values("Bust Weeks", ascending=False)
            )
            summary["Total Pts Lost"] = summary["Total Pts Lost"].round(1)
            st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── Duds Leaderboard ────────────────────────────────────────────────────
    with tab_duds:
        st.subheader("Duds Leaderboard")
        st.caption(
            "Who had the most DNP/inactive starters? "
            "A 'dud' is a starter who scored ≤ 2 pts (likely injured, IR'd, or benched)."
        )

        all_dud_owners = sorted(busts["owner_name"].dropna().unique())
        sel_dud_owners = st.multiselect("Filter managers", all_dud_owners, default=all_dud_owners, key="inj_dud_mgr")
        busts_dud = busts[busts["owner_name"].isin(sel_dud_owners)]

        # All-time summary per manager
        dud_summary = (
            busts_dud.groupby("owner_name")
            .agg(
                total_duds=("player", "count"),
                seasons_affected=("season", "nunique"),
                unique_players=("player", "nunique"),
            )
            .reset_index()
            .rename(columns={
                "owner_name": "Manager",
                "total_duds": "Total Duds",
                "seasons_affected": "Seasons",
                "unique_players": "Unique Players",
            })
            .sort_values("Total Duds", ascending=False)
        )

        fig_duds = px.bar(
            dud_summary.sort_values("Total Duds", ascending=True),
            x="Total Duds", y="Manager", orientation="h",
            color="Total Duds",
            color_continuous_scale="OrRd",
            title="All-Time Dud Starters by Manager",
        )
        fig_duds.update_coloraxes(showscale=False)
        fig_duds.update_layout(height=max(350, len(dud_summary) * 35))
        st.plotly_chart(fig_duds, use_container_width=True)
        st.dataframe(dud_summary, use_container_width=True, hide_index=True)

        st.divider()

        # Per-season breakdown
        st.subheader("Duds Per Season")
        dud_by_season = (
            busts_dud.groupby(["season", "owner_name"])
            .size()
            .reset_index(name="duds")
            .rename(columns={"owner_name": "Manager"})
        )
        pivot_duds = dud_by_season.pivot_table(index="Manager", columns="season", values="duds", fill_value=0)
        pivot_duds["Total"] = pivot_duds.sum(axis=1)
        pivot_duds = pivot_duds.sort_values("Total", ascending=False)
        st.dataframe(pivot_duds, use_container_width=True)

        st.divider()

        # Worst single weeks (most duds in one week by one manager)
        st.subheader("Worst Dud Weeks")
        worst_weeks = (
            busts_dud.groupby(["season", "week", "owner_name"])
            .size()
            .reset_index(name="duds_in_week")
            .rename(columns={"owner_name": "Manager"})
            .nlargest(20, "duds_in_week")
        )
        worst_weeks["week"] = worst_weeks["week"].astype(int) if worst_weeks["week"].dtype != object else worst_weeks["week"]
        st.dataframe(worst_weeks, use_container_width=True, hide_index=True)

    # ── Injury Timing ───────────────────────────────────────────────────────
    with tab_timing:
        all_timing_owners = sorted(busts["owner_name"].dropna().unique())
        sel_timing_owners = st.multiselect("Filter managers", all_timing_owners, default=all_timing_owners, key="inj_timing_mgr")
        busts_timing = busts[busts["owner_name"].isin(sel_timing_owners)]

        # --- Bust events chart ---
        st.subheader("Bust Events by Week")
        bust_by_week = (
            busts_timing.groupby(["season", "week"])
            .size()
            .reset_index(name="bust_events")
        )
        bust_by_week["season"] = bust_by_week["season"].astype(str)
        bust_by_week["week"] = bust_by_week["week"].astype(int)
        fig_bw = px.scatter(
            bust_by_week,
            x="week", y="bust_events",
            color="season",
            size="bust_events",
            labels={"week": "Week", "bust_events": "Bust Events", "season": "Season"},
            title="Bust/DNP starter events per week",
        )
        fig_bw.update_layout(xaxis=dict(tickmode="linear", dtick=1))
        st.plotly_chart(fig_bw, use_container_width=True)

        st.divider()
        st.subheader("Did bust events cost wins?")
        st.caption("Weeks with a bust starter — did the manager win or lose?")

        team_a = matchups_df[["season", "week", "team_a_owner", "winner_team_id", "team_a_id"]].rename(
            columns={"team_a_owner": "owner", "team_a_id": "my_id"}
        )
        team_b = matchups_df[["season", "week", "team_b_owner", "winner_team_id", "team_b_id"]].rename(
            columns={"team_b_owner": "owner", "team_b_id": "my_id"}
        )
        all_games = pd.concat([team_a, team_b], ignore_index=True)
        all_games["won"] = all_games["winner_team_id"] == all_games["my_id"]

        bust_weeks = (
            busts_timing[["season", "week", "owner_name", "player", "projected", "points"]]
            .merge(all_games[["season", "week", "owner", "won"]],
                   left_on=["season", "week", "owner_name"],
                   right_on=["season", "week", "owner"], how="left")
            .dropna(subset=["won"])
        )

        if bust_weeks.empty:
            st.info("Could not match bust weeks to matchup results.")
        else:
            unique_weeks = bust_weeks[["season", "week", "owner_name", "won"]].drop_duplicates()
            total = len(unique_weeks)
            lost = int((unique_weeks["won"] == False).sum())
            won = total - lost

            c1, c2, c3 = st.columns(3)
            c1.metric("Weeks with bust starter", total)
            c2.metric("Won despite bust", won)
            c3.metric("Lost with bust starter", lost)

            st.divider()
            loss_rows = unique_weeks[unique_weeks["won"] == False].merge(
                bust_weeks[["season", "week", "owner_name", "player", "projected", "points"]],
                on=["season", "week", "owner_name"],
            ).rename(columns={
                "owner_name": "Manager", "player": "Bust Player",
                "projected": "Proj", "points": "Actual",
            })
            loss_rows["Proj"] = loss_rows["Proj"].round(1)
            loss_rows["Actual"] = loss_rows["Actual"].round(1)
            if not loss_rows.empty:
                st.subheader("Loss weeks with bust starters")
                st.dataframe(loss_rows.drop(columns=["won"]).sort_values(["season", "week"]),
                             use_container_width=True, hide_index=True)

        st.divider()

        # --- Season injury impact: estimated points lost per manager ---
        st.subheader("Season Injury Impact — Points Lost")
        st.caption(
            "For each bust/DNP week, estimated points lost = player's healthy-week avg "
            "that season minus actual. Aggregated per manager per season."
        )
        _render_season_injury_impact(busts_timing, rosters_df)

        st.divider()
        _render_draft_injuries(conn, rosters_df)
