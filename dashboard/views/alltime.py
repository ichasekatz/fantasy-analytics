"""All-time records page: leaderboards, streaks, and historical milestones."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.bad_beats import bad_beat_index
from fantasy.analytics.records import all_records
from fantasy.analytics.standings import career_standings, season_standings
from utils import apply_league_filter, style_dataframe


def _avg_season_rank(matchups_df: pd.DataFrame, lid: str | None) -> pd.DataFrame:
    seasons = sorted(matchups_df["season"].dropna().unique())
    rows = []
    for s in seasons:
        st_df = season_standings(matchups_df, int(s), lid)
        if st_df.empty:
            continue
        n = len(st_df)
        pf_ranks = st_df["points_for"].fillna(0).rank(ascending=False, method="min").astype(int)
        pa_ranks = st_df["points_against"].fillna(0).rank(ascending=True, method="min").astype(int)
        for rank, (idx, row) in enumerate(st_df.iterrows(), start=1):
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
    for col in ("avg_finish", "avg_pct_rank", "avg_win_pct", "avg_pf_pct_rank", "avg_pa_pct_rank"):
        summary[col] = summary[col].round(3)
    return summary.sort_values("avg_pct_rank", ascending=False).reset_index(drop=True)


def render(conn) -> None:
    """Render the All-Time Records page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏆 All-Time Records")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    lid = st.session_state.get("selected_league_id")

    tab1, tab_rank, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Career Leaderboards", "Avg Season Rank", "Single-Game Records", "Streaks", "Championships", "💔 Bad Beats", "📖 Full Record Book"])

    with tab1:
        career = career_standings(matchups_df)
        min_seasons_filter = st.session_state.get("min_seasons_played", 1)
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
            has_ties_at = "h2h_ties" in career.columns and career["h2h_ties"].sum() > 0
            at_cols = ["Rank", "owner", "h2h_wins", "h2h_losses"]
            if has_ties_at:
                at_cols.append("h2h_ties")
            at_cols += ["h2h_win_pct", "pf_rank_12", "pa_rank_12", "seasons_played"]
            at_rename = {
                "owner": "Owner", "h2h_wins": "W", "h2h_losses": "L", "h2h_ties": "T",
                "h2h_win_pct": "Win%", "pf_rank_12": "Avg PF Rank",
                "pa_rank_12": "Avg PA Rank", "seasons_played": "Seasons",
            }
            display = career[[c for c in at_cols if c in career.columns]].rename(columns=at_rename)
            display["Win%"] = display["Win%"].round(3)
            if "Avg PF Rank" in display.columns:
                display["Avg PF Rank"] = display["Avg PF Rank"].round(1)
            if "Avg PA Rank" in display.columns:
                display["Avg PA Rank"] = display["Avg PA Rank"].round(1)
            styled_at = style_dataframe(
                display,
                higher_is_better=["W", "Win%", "Seasons"],
                lower_is_better=["L", "Avg PF Rank", "Avg PA Rank"],
            )
            st.dataframe(styled_at, use_container_width=True, hide_index=True)
            st.caption("PF/PA Rank: 1 = best, 12 = worst, normalized to 12-team scale.")

            all_owners_career = sorted(career["owner"].dropna().unique())
            sel_owners_career = st.multiselect(
                "Filter managers", all_owners_career, default=all_owners_career, key="alltime_career_mgr"
            )
            career_filtered = career[career["owner"].isin(sel_owners_career)]
            fig = px.bar(
                career_filtered.sort_values("h2h_wins", ascending=True),
                x="h2h_wins", y="owner", orientation="h",
                labels={"owner": "Manager", "h2h_wins": "Career Wins"},
                color_discrete_sequence=["#1f77b4"],
            )
            fig.update_layout(height=max(350, len(career_filtered) * 30), yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

    with tab_rank:
        st.caption(
            "Average finish per season, normalized for field size. "
            "Avg Pct Rank: 1.0 = finished 1st every year, 0.0 = last every year. "
            "PF/PA Rank: 1 = best (top scorer / fewest points against), 12 = worst, normalized to 12-team scale."
        )
        rank_df = _avg_season_rank(matchups_df, lid)
        min_seasons_filter = st.session_state.get("min_seasons_played", 1)
        if "seasons" in rank_df.columns and min_seasons_filter > 1:
            rank_df = rank_df[rank_df["seasons"] >= min_seasons_filter].reset_index(drop=True)
        if rank_df.empty:
            st.info("No data.")
        else:
            # Convert pct_ranks to 12-team scale
            if "avg_pf_pct_rank" in rank_df.columns:
                rank_df["pf_rank_12"] = (1 + (1 - rank_df["avg_pf_pct_rank"]) * 11).round(1)
            if "avg_pa_pct_rank" in rank_df.columns:
                rank_df["pa_rank_12"] = (1 + rank_df["avg_pa_pct_rank"] * 11).round(1)

            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            cols_to_show = ["Rank", "owner", "avg_finish", "best_finish", "worst_finish",
                            "avg_pct_rank", "avg_win_pct"]
            rename_map = {
                "owner": "Manager", "avg_finish": "Avg Finish",
                "best_finish": "Best", "worst_finish": "Worst",
                "avg_pct_rank": "Avg Pct Rank", "avg_win_pct": "Avg Win%",
                "seasons": "Seasons", "season_list": "Seasons List",
                "pf_rank_12": "Avg PF Rank", "pa_rank_12": "Avg PA Rank",
            }
            if "pf_rank_12" in rank_df.columns:
                cols_to_show.append("pf_rank_12")
            if "pa_rank_12" in rank_df.columns:
                cols_to_show.append("pa_rank_12")
            cols_to_show += ["seasons", "season_list"]
            out = rank_df[[c for c in cols_to_show if c in rank_df.columns]].rename(columns=rename_map)
            styled = style_dataframe(
                out,
                higher_is_better=["Avg Pct Rank", "Avg Win%", "Seasons"],
                lower_is_better=["Avg Finish", "Best", "Worst", "Avg PF Rank", "Avg PA Rank"],
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab2:
        # Highest scoring game (single side)
        all_scores = pd.concat([
            matchups_df[["season", "week", "team_a_owner", "team_a_name", "points_a", "winner_team_id", "team_a_id"]].rename(
                columns={"team_a_owner": "owner", "team_a_name": "team", "points_a": "pts", "team_a_id": "team_id"}),
            matchups_df[["season", "week", "team_b_owner", "team_b_name", "points_b", "winner_team_id", "team_b_id"]].rename(
                columns={"team_b_owner": "owner", "team_b_name": "team", "points_b": "pts", "team_b_id": "team_id"}),
        ]).dropna(subset=["pts"])
        all_scores["won"] = all_scores["team_id"] == all_scores["winner_team_id"]

        st.subheader("Highest Single-Game Scores")
        top_scores = all_scores.nlargest(10, "pts")[["season", "week", "owner", "team", "pts", "won"]].rename(columns={
            "season": "Season", "week": "Week", "owner": "Owner", "team": "Team", "pts": "Points", "won": "Won?"
        })
        top_scores["Points"] = top_scores["Points"].round(2)
        st.dataframe(top_scores, use_container_width=True, hide_index=True)

        st.subheader("Most Points in a Loss")
        losses = all_scores[~all_scores["won"]].nlargest(10, "pts")[["season", "week", "owner", "team", "pts"]].rename(columns={
            "season": "Season", "week": "Week", "owner": "Owner", "team": "Team", "pts": "Points",
        })
        losses["Points"] = losses["Points"].round(2)
        st.dataframe(losses, use_container_width=True, hide_index=True)

        st.subheader("Fewest Points in a Win")
        wins = all_scores[all_scores["won"]].nsmallest(10, "pts")[["season", "week", "owner", "team", "pts"]].rename(columns={
            "season": "Season", "week": "Week", "owner": "Owner", "team": "Team", "pts": "Points",
        })
        wins["Points"] = wins["Points"].round(2)
        st.dataframe(wins, use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Win Streaks")
        reg = matchups_df[~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]].copy()
        reg = reg.sort_values(["team_a_owner", "season", "week"])

        streaks = _compute_streaks(matchups_df)
        if streaks:
            streak_df = pd.DataFrame(streaks).sort_values("max_win_streak", ascending=False)
            streak_display = streak_df.rename(columns={
                "owner": "Manager", "max_win_streak": "Longest Win Streak", "max_loss_streak": "Longest Loss Streak"
            })
            st.dataframe(streak_display, use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Championships")
        champ_q = """
            SELECT season,
                   team_a_owner AS champion, team_a_name AS champion_team,
                   team_b_owner AS runner_up,
                   ROUND(points_a, 2) AS pts_for, ROUND(points_b, 2) AS pts_against,
                   ROUND(points_a - points_b, 2) AS margin
            FROM matchups
            WHERE is_championship = TRUE
            ORDER BY season
        """
        champs = conn.execute(champ_q).df()
        if not champs.empty:
            # Fix: winner is not always team_a; check winner_team_id
            champs_full = apply_league_filter(conn.execute("""
                SELECT league_id, season,
                       CASE WHEN winner_team_id = team_a_id THEN team_a_owner ELSE team_b_owner END AS champion,
                       CASE WHEN winner_team_id = team_a_id THEN team_a_name ELSE team_b_name END AS champion_team,
                       CASE WHEN winner_team_id = team_a_id THEN team_b_owner ELSE team_a_owner END AS runner_up,
                       ROUND(GREATEST(points_a, points_b), 2) AS pts_for,
                       ROUND(LEAST(points_a, points_b), 2) AS pts_against,
                       ROUND(ABS(points_a - points_b), 2) AS margin
                FROM matchups
                WHERE is_championship = TRUE
                ORDER BY season
            """).df())
            st.dataframe(champs_full, use_container_width=True, hide_index=True)

            champ_counts = champs_full["champion"].value_counts().reset_index()
            champ_counts.columns = ["Manager", "Championships"]
            st.subheader("Championship Counts")
            st.dataframe(champ_counts, use_container_width=True, hide_index=True)

    with tab5:
        st.subheader("💔 Hall of Heartbreak")
        st.caption("Ranked by Bad Beat Score: high-scoring losses where the opponent had an outlier game. Playoff losses weighted 1.5×.")

        beats = bad_beat_index(matchups_df)
        if beats.empty:
            st.info("No matchup data available.")
        else:
            display = beats.head(25)[["rank", "season", "week", "loser", "loser_score", "winner", "winner_score", "margin", "loser_percentile", "winner_outlier_sigma", "is_playoff", "bad_beat_score"]].rename(columns={
                "rank": "#", "season": "Season", "week": "Wk",
                "loser": "Victim", "loser_score": "Victim Score",
                "winner": "Executioner", "winner_score": "Winner Score",
                "margin": "Margin", "loser_percentile": "Victim Pctl%",
                "winner_outlier_sigma": "Opp σ", "is_playoff": "Playoff?",
                "bad_beat_score": "Beat Score",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("The Worst of the Worst")
            for _, brow in beats.head(5).iterrows():
                playoff_tag = " 🏆 PLAYOFFS" if brow["is_playoff"] or brow["is_championship"] else ""
                pctl_display = 100 - brow["loser_percentile"]
                st.error(
                    f"**#{int(brow['rank'])}** — {brow['loser']} scored **{brow['loser_score']}** pts "
                    f"(top {pctl_display:.0f}th pctile) and LOST to {brow['winner']} "
                    f"({brow['winner_score']} pts, {brow['winner_outlier_sigma']:.1f}σ above avg) "
                    f"by {brow['margin']} pts — Season {int(brow['season'])} Wk {int(brow['week'])}{playoff_tag}"
                )

    with tab6:
        _render_record_book(conn, matchups_df)


def _compute_streaks(matchups_df: pd.DataFrame) -> list[dict]:
    """Compute longest win and loss streaks per manager across all seasons.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame.

    Returns:
        List of dicts with owner, max_win_streak, max_loss_streak.
    """
    reg = matchups_df[
        ~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]
    ].copy()
    reg = reg.dropna(subset=["week"]).sort_values(["season", "week"])

    owner_results: dict[str, list[bool]] = {}
    for _, row in reg.iterrows():
        for owner, team_id, won_id in [
            (row["team_a_owner"], row["team_a_id"], row["winner_team_id"]),
            (row["team_b_owner"], row["team_b_id"], row["winner_team_id"]),
        ]:
            if not owner:
                continue
            if owner not in owner_results:
                owner_results[owner] = []
            owner_results[owner].append(team_id == won_id)

    out = []
    for owner, results in owner_results.items():
        max_w = max_l = cur_w = cur_l = 0
        for won in results:
            if won:
                cur_w += 1
                cur_l = 0
            else:
                cur_l += 1
                cur_w = 0
            max_w = max(max_w, cur_w)
            max_l = max(max_l, cur_l)
        out.append({"owner": owner, "max_win_streak": max_w, "max_loss_streak": max_l})
    return out


def _render_record_book(conn, matchups_df: pd.DataFrame) -> None:
    """Render the full searchable record book using records.py analytics.

    Args:
        conn: Open DuckDB connection.
        matchups_df: Already-filtered matchups DataFrame.
    """
    st.subheader("📖 Full Record Book")
    st.caption("Every scoring, win/loss, matchup, consistency, season, draft, and lineup record.")

    lid: str | None = st.session_state.get("selected_league_id")
    rosters_df = conn.execute("SELECT * FROM rosters").df()
    draft_df = conn.execute("SELECT * FROM draft_picks").df()

    with st.spinner("Computing records…"):
        try:
            records = all_records(matchups_df, rosters_df, draft_df, league_id=lid)
        except Exception as exc:
            st.error(f"Record computation failed: {exc}")
            return

    if not records:
        st.info("No records available for the selected filter.")
        return

    # Search box
    search = st.text_input("Search records", placeholder="e.g. highest score, win streak…", key="rb_search")

    for category, entries in records.items():
        if not entries:
            continue

        # Filter by search
        if search:
            entries = [e for e in entries if search.lower() in e.get("record", "").lower()
                       or search.lower() in str(e.get("holder", "")).lower()]
            if not entries:
                continue

        with st.expander(f"**{category}** ({len(entries)} records)", expanded=not bool(search)):
            df = pd.DataFrame(entries)[["rank", "record", "holder", "value", "context"]]
            df = df.rename(columns={
                "rank": "#", "record": "Record", "holder": "Holder",
                "value": "Value", "context": "Context",
            })
            # Format value column
            df["Value"] = df["Value"].apply(
                lambda v: f"{v:.2f}" if isinstance(v, float) and not v.is_integer() else str(int(v)) if isinstance(v, float) else str(v)
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
