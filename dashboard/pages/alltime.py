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
from fantasy.analytics.standings import career_standings
from utils import apply_league_filter


def render(conn) -> None:
    """Render the All-Time Records page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏆 All-Time Records")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Career Leaderboards", "Single-Game Records", "Streaks", "Championships", "💔 Bad Beats", "📖 Full Record Book"])

    with tab1:
        career = career_standings(matchups_df)
        if career.empty:
            st.info("No career data available.")
        else:
            career.insert(0, "Rank", range(1, len(career) + 1))
            display = career[["Rank", "owner", "h2h_wins", "h2h_losses", "h2h_win_pct", "points_for", "avg_pf", "seasons_played"]].rename(columns={
                "owner": "Owner", "h2h_wins": "W", "h2h_losses": "L",
                "h2h_win_pct": "Win%", "points_for": "Total PF",
                "avg_pf": "Avg PF/Game", "seasons_played": "Seasons",
            })
            display["Win%"] = display["Win%"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
            display["Total PF"] = display["Total PF"].round(1)
            display["Avg PF/Game"] = display["Avg PF/Game"].round(1)
            st.dataframe(display, use_container_width=True, hide_index=True)

            fig = px.bar(
                career.head(15), x="owner", y="h2h_wins",
                labels={"owner": "Manager", "h2h_wins": "Career Wins"},
                color_discrete_sequence=["#1f77b4"],
            )
            st.plotly_chart(fig, use_container_width=True)

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
