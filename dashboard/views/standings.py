"""Season standings page: regular-season records and all-play standings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

import pandas as pd

import numpy as np

from fantasy.analytics.standings import all_play_records, career_standings, season_standings
from utils import apply_league_filter, style_dataframe


def _avg_season_rank(matchups_df: pd.DataFrame, lid: str | None) -> pd.DataFrame:
    """Return each manager's average finish rank per season (normalized)."""
    seasons = sorted(matchups_df["season"].dropna().unique())
    rows = []
    for s in seasons:
        st_df = season_standings(matchups_df, int(s), lid)
        if st_df.empty:
            continue
        n = len(st_df)
        # Rank PF descending (rank 1 = highest scorer) and PA descending (rank 1 = most points against)
        pf_ranks = st_df["points_for"].fillna(0).rank(ascending=False, method="min").astype(int)
        pa_ranks = st_df["points_against"].fillna(0).rank(ascending=False, method="min").astype(int)
        for rank, (idx, row) in enumerate(st_df.iterrows(), start=1):
            # Percentile rank: 1.0 = best, 0.0 = worst (normalized for field size)
            pct_rank = 1.0 - (rank - 1) / max(n - 1, 1)
            pf_r = int(pf_ranks.loc[idx])
            pa_r = int(pa_ranks.loc[idx])
            rows.append({
                "owner": row["owner"],
                "season": int(s),
                "finish": rank,
                "field_size": n,
                "pct_rank": pct_rank,
                "h2h_win_pct": row.get("h2h_win_pct", float("nan")),
                "total_wins": row.get("total_wins", 0),
                "points_for": row.get("points_for", 0),
                "pf_pct_rank": 1.0 - (pf_r - 1) / max(n - 1, 1),
                "pa_pct_rank": 1.0 - (pa_r - 1) / max(n - 1, 1),
            })
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    summary = (
        df.groupby("owner")
        .agg(
            seasons=("season", "count"),
            avg_finish=("finish", "mean"),
            best_finish=("finish", "min"),
            worst_finish=("finish", "max"),
            avg_pct_rank=("pct_rank", "mean"),
            avg_win_pct=("h2h_win_pct", "mean"),
            avg_pf_pct_rank=("pf_pct_rank", "mean"),
            avg_pa_pct_rank=("pa_pct_rank", "mean"),
            season_list=("season", lambda x: ", ".join(str(s) for s in sorted(x))),
        )
        .reset_index()
    )
    summary["avg_finish"] = summary["avg_finish"].round(2)
    summary["avg_pct_rank"] = summary["avg_pct_rank"].round(3)
    summary["avg_win_pct"] = summary["avg_win_pct"].round(3)
    summary["avg_pf_pct_rank"] = summary["avg_pf_pct_rank"].round(3)
    summary["avg_pa_pct_rank"] = summary["avg_pa_pct_rank"].round(3)
    return summary.sort_values("avg_pct_rank", ascending=False).reset_index(drop=True)


def _schedule_justice(matchups_df: pd.DataFrame, season: int, lid: str | None) -> None:
    """Show who got robbed / who snuck in based on all-play rank vs actual playoffs."""
    ap = all_play_records(matchups_df, season, league_id=lid)
    if ap.empty:
        return

    playoff_rows = matchups_df[
        (matchups_df["season"] == season) &
        matchups_df["is_playoff"].fillna(False)
    ]
    if lid:
        playoff_rows = playoff_rows[playoff_rows["league_id"] == lid]
    playoff_owners = set(playoff_rows["team_a_owner"].tolist()) | set(playoff_rows["team_b_owner"].tolist())

    if not playoff_owners:
        return  # season still in progress

    # Regular-season points for ranking
    reg = matchups_df[
        (matchups_df["season"] == season) &
        ~matchups_df["is_playoff"].fillna(False) &
        ~matchups_df["is_consolation"].fillna(False) &
        ~matchups_df["is_championship"].fillna(False)
    ]
    if lid:
        reg = reg[reg["league_id"] == lid]

    pts_a = reg[["team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"})
    pts_b = reg[["team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"})
    total_pts = pd.concat([pts_a, pts_b]).groupby("owner")["pts"].sum().reset_index(name="total_pts")

    ap = ap.merge(total_pts, on="owner", how="left")
    ap["made_playoffs"] = ap["owner"].isin(playoff_owners)
    ap["pts_rank"] = ap["total_pts"].rank(ascending=False, method="min").astype(int)

    n_playoff = len(playoff_owners)
    snubbed = ap[~ap["made_playoffs"]].sort_values("ap_win_pct", ascending=False)
    lucky_in = ap[ap["made_playoffs"]].sort_values("ap_win_pct", ascending=True)

    st.divider()
    st.subheader("⚖️ Schedule Justice")

    col_rob, col_luck = st.columns(2)
    with col_rob:
        st.markdown("**💔 Robbed — deserved playoffs, missed out**")
        for _, r in snubbed.head(3).iterrows():
            pts_note = f" · #{int(r['pts_rank'])} in scoring" if pd.notna(r.get("total_pts")) else ""
            st.error(
                f"**{r['owner']}** — {r['ap_win_pct']:.1%} all-play win%"
                f" (would've ranked #{int(r['ap_rank'])} of {len(ap)}){pts_note}"
            )

    with col_luck:
        st.markdown("**🍀 Lucky — made playoffs despite schedule help**")
        for _, r in lucky_in.head(3).iterrows():
            pts_note = f" · #{int(r['pts_rank'])} in scoring" if pd.notna(r.get("total_pts")) else ""
            st.warning(
                f"**{r['owner']}** — {r['ap_win_pct']:.1%} all-play win%"
                f" (would've ranked #{int(r['ap_rank'])} of {len(ap)}){pts_note}"
            )


def render(conn) -> None:
    """Render the Standings page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📊 Standings")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    seasons_df = apply_league_filter(conn.execute("SELECT season, provider FROM seasons ORDER BY season").df())
    seasons_df = seasons_df.drop_duplicates(subset=["season"])
    lid = st.session_state.get("selected_league_id")

    seasons = sorted(matchups_df["season"].unique())
    provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
    season_labels = ["All Time"] + [f"{s} ({provider_map.get(s, '?')})" for s in seasons]

    selected_label = st.selectbox("Season", season_labels, index=len(season_labels) - 1)
    all_time = selected_label == "All Time"
    selected_season = None if all_time else seasons[season_labels.index(selected_label) - 1]
    min_seasons_filter = st.session_state.get("min_seasons_played", 1)

    tab_labels = ["Regular Season Standings", "All-Play Standings"]
    if all_time:
        tab_labels.append("Avg Season Rank")
    tabs = st.tabs(tab_labels)
    tab1, tab2 = tabs[0], tabs[1]
    tab3 = tabs[2] if all_time else None

    with tab1:
        if all_time:
            career = career_standings(matchups_df, league_id=lid)
            if "seasons_played" in career.columns and min_seasons_filter > 1:
                career = career[career["seasons_played"] >= min_seasons_filter].reset_index(drop=True)
            if career.empty:
                st.info("No career data available.")
            else:
                career.insert(0, "Rank", range(1, len(career) + 1))
                display_cols = ["Rank", "owner", "h2h_wins", "h2h_losses", "h2h_ties", "h2h_win_pct", "total_wins", "points_for", "points_against", "avg_pf", "seasons_played"]
                rename = {
                    "owner": "Owner",
                    "h2h_wins": "H2H W", "h2h_losses": "H2H L", "h2h_ties": "T",
                    "h2h_win_pct": "H2H Win%", "total_wins": "Total W (inc. median)",
                    "points_for": "PF", "points_against": "PA", "avg_pf": "Avg PF",
                    "seasons_played": "Seasons",
                }
                out = career[[c for c in display_cols if c in career.columns]].rename(columns=rename)
                out["H2H Win%"] = out["H2H Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                out["PF"] = out["PF"].round(1)
                out["PA"] = out["PA"].round(1)
                out["Avg PF"] = out["Avg PF"].round(1)
                styled = style_dataframe(
                    out,
                    higher_is_better=["H2H W", "Total W (inc. median)", "PF", "Avg PF", "Seasons"],
                    lower_is_better=["H2H L"],
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("H2H Win% excludes median matchup games for fair cross-season comparison.")
        else:
            standings = season_standings(matchups_df, selected_season)
            if standings.empty:
                st.info("No regular-season data available.")
            else:
                standings.insert(0, "Rank", range(1, len(standings) + 1))
                has_median = "median_wins" in standings.columns and standings["median_wins"].sum() > 0
                display_cols = ["Rank", "owner", "team", "h2h_wins", "h2h_losses", "h2h_ties", "h2h_win_pct", "points_for", "points_against", "avg_pf"]
                rename = {
                    "owner": "Owner", "team": "Team",
                    "h2h_wins": "W", "h2h_losses": "L", "h2h_ties": "T",
                    "h2h_win_pct": "Win%", "points_for": "PF", "points_against": "PA", "avg_pf": "Avg PF",
                }
                if has_median:
                    display_cols += ["median_wins", "median_losses"]
                    rename["median_wins"] = "Med W"
                    rename["median_losses"] = "Med L"
                display_cols = [c for c in display_cols if c in standings.columns]
                out = standings[display_cols].rename(columns=rename)
                out["Win%"] = out["Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                out["PF"] = out["PF"].round(2)
                out["PA"] = out["PA"].round(2)
                out["Avg PF"] = out["Avg PF"].round(1)
                hib = ["W", "Win%", "PF", "Avg PF"] + (["Med W"] if has_median else [])
                lib = ["L"] + (["Med L"] if has_median else [])
                styled = style_dataframe(out, higher_is_better=hib, lower_is_better=lib)
                st.dataframe(styled, use_container_width=True, hide_index=True)
                if has_median:
                    st.caption("W/L = head-to-head. Med W/L = median matchup games.")

    with tab2:
        if all_time:
            st.info("All-play standings are per-season. Select a season to view.")
        else:
            ap = all_play_records(matchups_df, selected_season)
            if ap.empty:
                st.info("No all-play data available.")
            else:
                ap.insert(0, "Rank", range(1, len(ap) + 1))
                display_cols = ["Rank", "owner", "team", "ap_wins", "ap_losses", "ap_ties", "ap_win_pct"]
                rename = {
                    "owner": "Owner", "team": "Team",
                    "ap_wins": "AP W", "ap_losses": "AP L", "ap_ties": "AP T", "ap_win_pct": "AP Win%",
                }
                out = ap[display_cols].rename(columns=rename)
                out["AP Win%"] = out["AP Win%"].apply(lambda x: f"{x:.3f}" if x == x else "—")
                st.dataframe(out, use_container_width=True, hide_index=True)
                st.caption(
                    "All-play win% = how often each team would win if they played every other team each week. "
                    "Removes schedule luck."
                )

    if all_time and tab3 is not None:
        with tab3:
            st.caption(
                "Average finish position per season, normalized across different field sizes. "
                "Avg Pct Rank: 1.0 = finished 1st every season, 0.0 = last every season."
            )
            rank_df = _avg_season_rank(matchups_df, lid)
            if rank_df.empty:
                st.info("No data available.")
            else:
                # PF Rank - PA Rank: positive = higher scorer than you give up points (offensive)
                if "avg_pa_pct_rank" in rank_df.columns and "avg_pf_pct_rank" in rank_df.columns:
                    rank_df["pa_minus_pf"] = (rank_df["avg_pf_pct_rank"] - rank_df["avg_pa_pct_rank"]).round(3)

                display_df = rank_df[rank_df["seasons"] >= min_seasons_filter].copy() if "seasons" in rank_df.columns else rank_df.copy()
                display_df.insert(0, "Rank", range(1, len(display_df) + 1))

                cols_to_show = ["Rank", "owner", "avg_finish", "best_finish", "worst_finish",
                                "avg_pct_rank", "avg_win_pct"]
                rename_map = {
                    "owner": "Manager",
                    "avg_finish": "Avg Finish",
                    "best_finish": "Best",
                    "worst_finish": "Worst",
                    "avg_pct_rank": "Avg Pct Rank",
                    "avg_win_pct": "Avg Win%",
                    "seasons": "Seasons Played",
                    "season_list": "Seasons",
                    "pa_minus_pf": "PF Rank − PA Rank",
                }
                if "avg_pf_pct_rank" in display_df.columns:
                    cols_to_show.append("avg_pf_pct_rank")
                    rename_map["avg_pf_pct_rank"] = "Avg PF Rank"
                if "avg_pa_pct_rank" in display_df.columns:
                    cols_to_show.append("avg_pa_pct_rank")
                    rename_map["avg_pa_pct_rank"] = "Avg PA Rank"
                if "pa_minus_pf" in display_df.columns:
                    cols_to_show.append("pa_minus_pf")
                cols_to_show += ["seasons", "season_list"]
                out = display_df[[c for c in cols_to_show if c in display_df.columns]].rename(columns=rename_map)
                styled = style_dataframe(
                    out,
                    higher_is_better=["Avg Pct Rank", "Avg Win%", "Avg PF Rank", "Seasons Played"],
                    lower_is_better=["Avg Finish", "Best", "Worst", "Avg PA Rank"],
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("PF Rank − PA Rank: positive = higher scorer than you give up points (offensive); negative = more PA than PF rank (tougher schedule / lower scorer). Avg PA Rank: lower = fewer points against (better).")

    if not all_time:
        _schedule_justice(matchups_df, selected_season, lid)
