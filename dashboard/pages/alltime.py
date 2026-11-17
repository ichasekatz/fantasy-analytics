"""All-time records page: leaderboards, streaks, and historical milestones."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import career_standings


def render(conn) -> None:
    """Render the All-Time Records page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏆 All-Time Records")

    matchups_df = conn.execute("SELECT * FROM matchups").df()

    tab1, tab2, tab3, tab4 = st.tabs(["Career Leaderboards", "Single-Game Records", "Streaks", "Championships"])

    with tab1:
        career = career_standings(matchups_df)
        if career.empty:
            st.info("No career data available.")
        else:
            career.insert(0, "Rank", range(1, len(career) + 1))
            display = career[["Rank", "owner", "wins", "losses", "win_pct", "points_for", "avg_pf", "seasons_played"]].rename(columns={
                "owner": "Owner", "wins": "W", "losses": "L",
                "win_pct": "Win%", "points_for": "Total PF",
                "avg_pf": "Avg PF/Game", "seasons_played": "Seasons",
            })
            display["Win%"] = display["Win%"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
            display["Total PF"] = display["Total PF"].round(1)
            display["Avg PF/Game"] = display["Avg PF/Game"].round(1)
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Career Leaderboard CSV",
                display.to_csv(index=False).encode("utf-8"),
                "career_leaderboard.csv", "text/csv", key="dl_alltime_career",
            )

            fig = px.bar(
                career.head(15), x="owner", y="wins",
                labels={"owner": "Manager", "wins": "Career Wins"},
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
        st.download_button(
            "⬇️ Download Top Scores CSV",
            top_scores.to_csv(index=False).encode("utf-8"),
            "top_scores.csv", "text/csv", key="dl_alltime_top",
        )

        st.subheader("Most Points in a Loss")
        losses = all_scores[~all_scores["won"]].nlargest(10, "pts")[["season", "week", "owner", "team", "pts"]].rename(columns={
            "season": "Season", "week": "Week", "owner": "Owner", "team": "Team", "pts": "Points",
        })
        losses["Points"] = losses["Points"].round(2)
        st.dataframe(losses, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Most Points in Loss CSV",
            losses.to_csv(index=False).encode("utf-8"),
            "most_pts_loss.csv", "text/csv", key="dl_alltime_loss",
        )

        st.subheader("Fewest Points in a Win")
        wins = all_scores[all_scores["won"]].nsmallest(10, "pts")[["season", "week", "owner", "team", "pts"]].rename(columns={
            "season": "Season", "week": "Week", "owner": "Owner", "team": "Team", "pts": "Points",
        })
        wins["Points"] = wins["Points"].round(2)
        st.dataframe(wins, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Fewest Points in Win CSV",
            wins.to_csv(index=False).encode("utf-8"),
            "fewest_pts_win.csv", "text/csv", key="dl_alltime_win",
        )

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
            st.download_button(
                "⬇️ Download Streaks CSV",
                streak_display.to_csv(index=False).encode("utf-8"),
                "streaks.csv", "text/csv", key="dl_alltime_streaks",
            )

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
            champs_full = conn.execute("""
                SELECT season,
                       CASE WHEN winner_team_id = team_a_id THEN team_a_owner ELSE team_b_owner END AS champion,
                       CASE WHEN winner_team_id = team_a_id THEN team_a_name ELSE team_b_name END AS champion_team,
                       CASE WHEN winner_team_id = team_a_id THEN team_b_owner ELSE team_a_owner END AS runner_up,
                       ROUND(GREATEST(points_a, points_b), 2) AS pts_for,
                       ROUND(LEAST(points_a, points_b), 2) AS pts_against,
                       ROUND(ABS(points_a - points_b), 2) AS margin
                FROM matchups
                WHERE is_championship = TRUE
                ORDER BY season
            """).df()
            st.dataframe(champs_full, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download Championships CSV",
                champs_full.to_csv(index=False).encode("utf-8"),
                "championships.csv", "text/csv", key="dl_alltime_champs",
            )
            champ_counts = champs_full["champion"].value_counts().reset_index()
            champ_counts.columns = ["Manager", "Championships"]
            st.subheader("Championship Counts")
            st.dataframe(champ_counts, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download Champ Counts CSV",
                champ_counts.to_csv(index=False).encode("utf-8"),
                "champ_counts.csv", "text/csv", key="dl_alltime_champ_counts",
            )


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
