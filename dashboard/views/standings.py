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

    selected_label = st.selectbox("Season", season_labels, index=0)
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
                # Compute career avg PF/PA rank (12-team normalized)
                _career_rank_rows = []
                for _s in sorted(matchups_df["season"].dropna().unique()):
                    _sdf = season_standings(matchups_df, int(_s), lid)
                    if _sdf.empty:
                        continue
                    _sn = len(_sdf)
                    if _sn < 2:
                        continue
                    _pf_r2 = _sdf["points_for"].rank(ascending=False, method="min")
                    _pa_r2 = _sdf["points_against"].rank(ascending=True, method="min")
                    for _i, _row in _sdf.iterrows():
                        _career_rank_rows.append({
                            "owner": _row["owner"],
                            "pf_rank_12": 1 + (_pf_r2.loc[_i] - 1) / (_sn - 1) * 11,
                            "pa_rank_12": 1 + (_pa_r2.loc[_i] - 1) / (_sn - 1) * 11,
                        })
                if _career_rank_rows:
                    _cr_df = pd.DataFrame(_career_rank_rows).groupby("owner").agg(
                        pf_rank_12=("pf_rank_12", "mean"), pa_rank_12=("pa_rank_12", "mean")
                    ).reset_index()
                    career = career.merge(_cr_df, on="owner", how="left")

                career.insert(0, "Rank", range(1, len(career) + 1))
                has_ties = "h2h_ties" in career.columns and career["h2h_ties"].sum() > 0
                display_cols = ["Rank", "owner", "h2h_wins", "h2h_losses"]
                if has_ties:
                    display_cols.append("h2h_ties")
                display_cols += ["h2h_win_pct", "total_wins", "pf_rank_12", "pa_rank_12", "seasons_played"]
                rename = {
                    "owner": "Owner",
                    "h2h_wins": "H2H W", "h2h_losses": "H2H L", "h2h_ties": "T",
                    "h2h_win_pct": "H2H Win%", "total_wins": "Total W (inc. median)",
                    "pf_rank_12": "Avg PF Rank", "pa_rank_12": "Avg PA Rank",
                    "seasons_played": "Seasons",
                }
                out = career[[c for c in display_cols if c in career.columns]].rename(columns=rename)
                out["H2H Win%"] = out["H2H Win%"].round(3)
                if "Avg PF Rank" in out.columns:
                    out["Avg PF Rank"] = out["Avg PF Rank"].round(1)
                if "Avg PA Rank" in out.columns:
                    out["Avg PA Rank"] = out["Avg PA Rank"].round(1)
                styled = style_dataframe(
                    out,
                    higher_is_better=["H2H W", "Total W (inc. median)", "H2H Win%", "Seasons"],
                    lower_is_better=["H2H L", "Avg PF Rank", "Avg PA Rank"],
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("H2H Win% excludes median matchup games for fair cross-season comparison. PF/PA Rank: 1 = best (top scorer / fewest points against), 12 = worst, normalized to 12-team scale.")
        else:
            standings = season_standings(matchups_df, selected_season)
            if standings.empty:
                st.info("No regular-season data available.")
            else:
                standings.insert(0, "Rank", range(1, len(standings) + 1))
                has_median = "median_wins" in standings.columns and standings["median_wins"].sum() > 0
                has_ties = "h2h_ties" in standings.columns and standings["h2h_ties"].sum() > 0
                # 12-team normalized PF/PA ranks
                _n = len(standings)
                if _n > 1:
                    _pf_r = standings["points_for"].rank(ascending=False, method="min")
                    _pa_r = standings["points_against"].rank(ascending=True, method="min")
                    standings["PF Rank"] = (1 + (_pf_r - 1) / (_n - 1) * 11).round(1)
                    standings["PA Rank"] = (1 + (_pa_r - 1) / (_n - 1) * 11).round(1)
                else:
                    standings["PF Rank"] = 1.0
                    standings["PA Rank"] = 1.0
                display_cols = ["Rank", "owner", "team", "h2h_wins", "h2h_losses"]
                if has_ties:
                    display_cols.append("h2h_ties")
                display_cols += ["h2h_win_pct", "PF Rank", "PA Rank"]
                rename = {
                    "owner": "Owner", "team": "Team",
                    "h2h_wins": "W", "h2h_losses": "L", "h2h_ties": "T",
                    "h2h_win_pct": "Win%",
                }
                if has_median:
                    display_cols += ["median_wins", "median_losses"]
                    rename["median_wins"] = "Med W"
                    rename["median_losses"] = "Med L"
                display_cols = [c for c in display_cols if c in standings.columns]
                out = standings[display_cols].rename(columns=rename)
                out["Win%"] = out["Win%"].round(3)
                hib = ["W", "Win%"] + (["Med W"] if has_median else [])
                lib = ["L", "PF Rank", "PA Rank"] + (["Med L"] if has_median else [])
                styled = style_dataframe(out, higher_is_better=hib, lower_is_better=lib)
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("PF/PA Rank: 1 = best (top scorer / fewest points against), normalized to 12-team scale." + (" W/L = head-to-head. Med W/L = median matchup games." if has_median else ""))

    with tab2:
        if all_time:
            # Aggregate all-play records across all seasons
            all_ap_rows = []
            for _s in sorted(matchups_df["season"].dropna().unique()):
                _ap = all_play_records(matchups_df, int(_s))
                if not _ap.empty:
                    all_ap_rows.append(_ap[["owner", "ap_wins", "ap_losses"]].copy())
            if not all_ap_rows:
                st.info("No all-play data available.")
            else:
                combined_ap = pd.concat(all_ap_rows, ignore_index=True)
                career_ap = combined_ap.groupby("owner").agg(
                    ap_wins=("ap_wins", "sum"),
                    ap_losses=("ap_losses", "sum"),
                ).reset_index()
                career_ap["ap_win_pct"] = (
                    career_ap["ap_wins"] / (career_ap["ap_wins"] + career_ap["ap_losses"]).replace(0, pd.NA)
                ).round(3)
                # Attach seasons_played for min_seasons filter
                seasons_per_ap = (
                    pd.concat([_ap[["owner"]].assign(season=int(_s))
                               for _s in sorted(matchups_df["season"].dropna().unique())
                               for _ap in [all_play_records(matchups_df, int(_s))]
                               if not _ap.empty], ignore_index=True)
                    .groupby("owner")["season"].nunique()
                    .reset_index(name="seasons_played")
                )
                career_ap = career_ap.merge(seasons_per_ap, on="owner", how="left")
                if min_seasons_filter > 1 and "seasons_played" in career_ap.columns:
                    career_ap = career_ap[career_ap["seasons_played"] >= min_seasons_filter]
                career_ap = career_ap.sort_values("ap_win_pct", ascending=False).reset_index(drop=True)
                career_ap.insert(0, "Rank", range(1, len(career_ap) + 1))
                out_ap = career_ap[["Rank", "owner", "ap_wins", "ap_losses", "ap_win_pct", "seasons_played"]].rename(columns={
                    "owner": "Owner", "ap_wins": "AP W", "ap_losses": "AP L",
                    "ap_win_pct": "AP Win%", "seasons_played": "Seasons",
                })
                styled_ap = style_dataframe(out_ap, higher_is_better=["AP W", "AP Win%", "Seasons"], lower_is_better=["AP L", "Rank"])
                st.dataframe(styled_ap, use_container_width=True, hide_index=True)
                st.caption("All-play win% across all seasons. Removes schedule luck.")
        else:
            ap = all_play_records(matchups_df, selected_season)
            if ap.empty:
                st.info("No all-play data available.")
            else:
                ap.insert(0, "Rank", range(1, len(ap) + 1))
                has_ap_ties = "ap_ties" in ap.columns and ap["ap_ties"].sum() > 0
                display_cols = ["Rank", "owner", "team", "ap_wins", "ap_losses"]
                if has_ap_ties:
                    display_cols.append("ap_ties")
                display_cols.append("ap_win_pct")
                rename = {
                    "owner": "Owner", "team": "Team",
                    "ap_wins": "AP W", "ap_losses": "AP L", "ap_ties": "AP T", "ap_win_pct": "AP Win%",
                }
                out = ap[[c for c in display_cols if c in ap.columns]].rename(columns=rename)
                out["AP Win%"] = out["AP Win%"].round(3)
                styled_ap = style_dataframe(out, higher_is_better=["AP W", "AP Win%"], lower_is_better=["AP L"])
                st.dataframe(styled_ap, use_container_width=True, hide_index=True)
                st.caption(
                    "All-play win% = how often each team would win if they played every other team each week. "
                    "Removes schedule luck."
                )

    if all_time and tab3 is not None:
        with tab3:
            st.caption(
                "Average finish per season, normalized for field size. "
                "Avg Pct Rank: 1.0 = finished 1st every season, 0.0 = last every season. "
                "PF/PA Rank: 1 = best (top scorer / fewest points against), 12 = worst, normalized to 12-team scale."
            )
            rank_df = _avg_season_rank(matchups_df, lid)
            if rank_df.empty:
                st.info("No data available.")
            else:
                # Convert pct_ranks to 12-team scale (1=best, 12=worst)
                if "avg_pf_pct_rank" in rank_df.columns:
                    rank_df["pf_rank_12"] = (1 + (1 - rank_df["avg_pf_pct_rank"]) * 11).round(1)
                if "avg_pa_pct_rank" in rank_df.columns:
                    rank_df["pa_rank_12"] = (1 + rank_df["avg_pa_pct_rank"] * 11).round(1)
                if "pf_rank_12" in rank_df.columns and "pa_rank_12" in rank_df.columns:
                    rank_df["pa_minus_pf_12"] = (rank_df["pa_rank_12"] - rank_df["pf_rank_12"]).round(1)

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
                    "pf_rank_12": "Avg PF Rank",
                    "pa_rank_12": "Avg PA Rank",
                    "pa_minus_pf_12": "PA Rank − PF Rank",
                }
                if "pf_rank_12" in display_df.columns:
                    cols_to_show.append("pf_rank_12")
                if "pa_rank_12" in display_df.columns:
                    cols_to_show.append("pa_rank_12")
                if "pa_minus_pf_12" in display_df.columns:
                    cols_to_show.append("pa_minus_pf_12")
                cols_to_show += ["seasons", "season_list"]
                out = display_df[[c for c in cols_to_show if c in display_df.columns]].rename(columns=rename_map)
                styled = style_dataframe(
                    out,
                    higher_is_better=["Avg Pct Rank", "Avg Win%", "Seasons Played"],
                    lower_is_better=["Avg Finish", "Best", "Worst", "Avg PF Rank", "Avg PA Rank"],
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("PA Rank − PF Rank: positive = more points against than you score (tough schedule / lower scorer); negative = outscoring more than you give up (offensive team).")

    if not all_time:
        _schedule_justice(matchups_df, selected_season, lid)
