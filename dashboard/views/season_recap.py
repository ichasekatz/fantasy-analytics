"""Fantasy Wrapped: personalized season recap for each manager."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.draft_analytics import manager_draft_grades
from fantasy.analytics.luck import luck_metrics
from fantasy.analytics.standings import season_standings
from style import inject_css
from utils import apply_league_filter


def render(conn) -> None:
    inject_css()
    st.title("🎁 Fantasy Wrapped")
    st.caption("Your personalized season-by-season recap.")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    seasons = sorted(matchups_df["season"].dropna().unique(), reverse=True)
    col1, col2 = st.columns(2)
    with col1:
        selected_season = st.selectbox("Season", seasons, key="wrapped_season")

    season_matchups = matchups_df[matchups_df["season"] == selected_season]
    all_owners = sorted(set(
        season_matchups["team_a_owner"].dropna().tolist()
        + season_matchups["team_b_owner"].dropna().tolist()
    ))
    with col2:
        selected_manager = st.selectbox("Manager", all_owners, key="wrapped_manager")

    if not st.button("🎁 Generate Recap", type="primary"):
        st.info("Select a season and manager, then click Generate Recap.")
        return

    lid: str | None = st.session_state.get("selected_league_id")
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks").df())

    _render_recap(season_matchups, rosters_df, draft_df, matchups_df, selected_manager, int(selected_season), lid)


def _render_recap(
    season_matchups: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_df: pd.DataFrame,
    full_matchups: pd.DataFrame,
    manager: str,
    season: int,
    lid: str | None,
) -> None:
    reg = season_matchups[
        ~season_matchups["is_playoff"].fillna(False)
        & ~season_matchups["is_championship"].fillna(False)
        & ~season_matchups["is_consolation"].fillna(False)
    ]

    # Build per-game records for this manager
    games_a = reg[reg["team_a_owner"] == manager][["week", "points_a", "points_b", "team_b_owner", "winner_team_id", "team_a_id"]].rename(
        columns={"points_a": "pf", "points_b": "pa", "team_b_owner": "opponent", "team_a_id": "my_id"}
    )
    games_b = reg[reg["team_b_owner"] == manager][["week", "points_b", "points_a", "team_a_owner", "winner_team_id", "team_b_id"]].rename(
        columns={"points_b": "pf", "points_a": "pa", "team_a_owner": "opponent", "team_b_id": "my_id"}
    )
    games = pd.concat([games_a, games_b]).dropna(subset=["pf"])
    games["won"] = games["my_id"] == games["winner_team_id"]

    if games.empty:
        st.warning(f"No regular-season games found for {manager} in {season}.")
        return

    wins = int(games["won"].sum())
    losses = int((~games["won"]).sum())
    pf = round(games["pf"].sum(), 1)
    pa = round(games["pa"].sum(), 1)

    # Standings rank
    standings = season_standings(full_matchups, season, lid)
    rank = None
    if not standings.empty and "owner" in standings.columns:
        match = standings[standings["owner"] == manager]
        if not match.empty:
            rank = int(standings.index[standings["owner"] == manager][0]) + 1
    n_teams = len(standings) if not standings.empty else "?"

    # Championship status
    champ_rows = season_matchups[season_matchups["is_championship"].fillna(False)]
    is_champion = False
    is_runner_up = False
    if not champ_rows.empty:
        row = champ_rows.iloc[0]
        winner = row["team_a_owner"] if row["winner_team_id"] == row["team_a_id"] else row["team_b_owner"]
        loser = row["team_b_owner"] if winner == row["team_a_owner"] else row["team_a_owner"]
        is_champion = winner == manager
        is_runner_up = loser == manager

    if is_champion:
        st.balloons()
        st.success(f"🏆 {manager} won the {season} championship!")
    elif is_runner_up:
        st.warning(f"🥈 {manager} was the {season} runner-up.")

    st.divider()
    st.subheader(f"{manager} — {season} Season")

    # --- Row 1: Final Record ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Record", f"{wins}–{losses}")
    c2.metric("Final Standing", f"#{rank} of {n_teams}" if rank else "?")
    c3.metric("Points For", f"{pf:,.1f}")
    c4.metric("Points Against", f"{pa:,.1f}")

    st.divider()

    # --- Row 2: Luck ---
    try:
        luck = luck_metrics(full_matchups, season, lid)
        if not luck.empty and "owner" in luck.columns:
            my_luck = luck[luck["owner"] == manager]
            if not my_luck.empty:
                r = my_luck.iloc[0]
                luck_rank = int(luck["luck_delta"].rank(ascending=False).iloc[luck.index[luck["owner"] == manager][0]])
                st.subheader("🍀 Schedule Luck")
                lc1, lc2, lc3 = st.columns(3)
                lc1.metric("Actual Wins", wins)
                lc2.metric("Expected Wins", f"{r.get('expected_wins', 0):.1f}")
                delta = r.get("luck_delta", 0)
                lc3.metric("Luck Delta", f"{delta:+.1f}", delta_color="normal")
                if delta > 1:
                    st.success(f"You were the #{luck_rank} luckiest team — benefited from an easy schedule.")
                elif delta < -1:
                    st.error(f"You were the #{luck_rank} unluckiest team — deserved better.")
                else:
                    st.info("Your schedule was about average.")
    except Exception:
        pass

    st.divider()

    # --- Row 3: Draft ---
    try:
        grades = manager_draft_grades(draft_df, rosters_df, season=season, league_id=lid)
        if not grades.empty and "owner_name" in grades.columns:
            my_grade = grades[grades["owner_name"] == manager]
            if not my_grade.empty:
                g = my_grade.iloc[0]
                st.subheader("🎯 Draft Report Card")
                st.caption("**VORP** = Value Over Replacement Player: points scored above an average player at that pick slot.")
                dc1, dc2, dc3, dc4 = st.columns(4)
                dc1.metric("Draft Rank", f"#{int(g.get('draft_rank', 0))} of {len(grades)}")
                dc2.metric("Total VORP", f"{g.get('total_draft_vorp', 0):.1f}")
                dc3.metric("Steals", int(g.get("steals_count", 0)))
                dc4.metric("Busts", int(g.get("busts_count", 0)))
    except Exception:
        pass

    st.divider()

    # --- Row 4: Weekly highs/lows ---
    if not games.empty:
        st.subheader("📊 Weekly Highlights")
        best_week = games.loc[games["pf"].idxmax()]
        worst_week = games.loc[games["pf"].idxmin()]
        worst_loss = games[~games["won"]].nlargest(1, "pf")

        wc1, wc2 = st.columns(2)
        with wc1:
            result_str = "W" if best_week["won"] else "L"
            st.metric("Best Week", f"Wk {int(best_week['week'])}: {best_week['pf']:.1f} pts ({result_str})")
            st.caption(f"vs {best_week['opponent']}")
        with wc2:
            result_str2 = "W" if worst_week["won"] else "L"
            st.metric("Worst Week", f"Wk {int(worst_week['week'])}: {worst_week['pf']:.1f} pts ({result_str2})")
            st.caption(f"vs {worst_week['opponent']}")

        if not worst_loss.empty:
            pl = worst_loss.iloc[0]
            st.warning(f"💔 Most Painful Loss: Week {int(pl['week'])} — scored {pl['pf']:.1f} pts but lost to {pl['opponent']} ({pl['pa']:.1f} pts)")

    st.divider()

    # --- Row 5: Best player ---
    my_rosters = rosters_df[
        (rosters_df["owner_name"] == manager) &
        (rosters_df["season"] == season) &
        rosters_df["starter"].fillna(False)
    ]
    if not my_rosters.empty:
        st.subheader("🌟 Best Player")
        player_pts = my_rosters.groupby("player")["points"].sum().sort_values(ascending=False)
        if not player_pts.empty:
            best_player = player_pts.index[0]
            best_pts = round(player_pts.iloc[0], 1)
            pos = my_rosters[my_rosters["player"] == best_player]["position"].iloc[0] if len(my_rosters[my_rosters["player"] == best_player]) > 0 else "?"
            st.success(f"🌟 **{best_player}** ({pos}) — {best_pts} started points")

        # Bench disaster
        all_my = rosters_df[(rosters_df["owner_name"] == manager) & (rosters_df["season"] == season)]
        worst_bench_week = None
        worst_missed = 0
        for wk, wk_df in all_my.groupby("week"):
            starters = wk_df[wk_df["starter"].fillna(False)]
            bench = wk_df[~wk_df["starter"].fillna(False)]
            if starters.empty or bench.empty:
                continue
            actual = starters["points"].sum()
            n_starters = len(starters)
            all_pts = wk_df["points"].dropna().nlargest(n_starters).sum()
            missed = round(all_pts - actual, 1)
            if missed > worst_missed:
                worst_missed = missed
                worst_bench_week = wk
        if worst_bench_week and worst_missed > 0:
            st.error(f"🪑 Bench Disaster: Week {int(worst_bench_week)} — left {worst_missed:.1f} pts on bench")

    st.divider()

    # --- Season Summary ---
    st.subheader("📋 Season Summary")
    bullets = []
    bullets.append(f"Finished **{wins}–{losses}** (#{rank} of {n_teams})" if rank else f"Finished **{wins}–{losses}**")
    bullets.append(f"Scored **{pf:.1f}** total points (**{pf/max(wins+losses,1):.1f}** avg/week)")
    if not games.empty:
        win_rate = wins / max(wins + losses, 1)
        if win_rate >= 0.6:
            bullets.append("Strong regular season performance.")
        elif win_rate <= 0.35:
            bullets.append("Tough season — struggled to find consistency.")

    for b in bullets:
        st.markdown(f"- {b}")
