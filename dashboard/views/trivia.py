"""League Trivia: database-backed multiple-choice trivia from real league data."""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from style import inject_css
from utils import apply_league_filter


@dataclass
class TriviaQuestion:
    question: str
    answer: str
    answer_display: str
    category: str
    difficulty: str
    context: str
    options: list[str]


def _generate_questions(matchups_df: pd.DataFrame, rosters_df: pd.DataFrame, draft_df: pd.DataFrame) -> list[TriviaQuestion]:
    questions: list[TriviaQuestion] = []

    all_owners = sorted(set(
        matchups_df["team_a_owner"].dropna().tolist()
        + matchups_df["team_b_owner"].dropna().tolist()
    ))
    seasons = sorted(matchups_df["season"].dropna().unique())

    # --- SCORING QUESTIONS ---

    # Highest single-week score
    all_scores = pd.concat([
        matchups_df[["season", "week", "team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
        matchups_df[["season", "week", "team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
    ]).dropna(subset=["pts"])
    if not all_scores.empty and all_scores["pts"].notna().any():
        top_row = all_scores.nlargest(1, "pts").iloc[0]
        answer = str(top_row["owner"])
        wrong = [o for o in all_owners if o != answer][:3]
        opts = wrong + [answer]
        random.shuffle(opts)
        questions.append(TriviaQuestion(
            question=f"Who scored the most points in a single week ({top_row['pts']:.1f} pts)?",
            answer=answer,
            answer_display=answer,
            category="Scoring",
            difficulty="medium",
            context=f"Season {int(top_row['season'])}, Week {int(top_row['week'])}: {top_row['pts']:.1f} pts",
            options=opts,
        ))

        # Highest season total
        season_totals = all_scores.groupby("owner")["pts"].sum()
        top_season_owner = season_totals.idxmax()
        wrong2 = [o for o in all_owners if o != top_season_owner][:3]
        opts2 = wrong2 + [top_season_owner]
        random.shuffle(opts2)
        questions.append(TriviaQuestion(
            question="Who has the most total points across all seasons?",
            answer=top_season_owner,
            answer_display=top_season_owner,
            category="Scoring",
            difficulty="hard",
            context=f"{top_season_owner} scored {season_totals[top_season_owner]:.1f} total points",
            options=opts2,
        ))

        # Fewest points in a win
        reg = matchups_df[~matchups_df["is_playoff"].fillna(False)]
        wins_a = reg[reg["winner_team_id"] == reg["team_a_id"]][["team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"})
        wins_b = reg[reg["winner_team_id"] == reg["team_b_id"]][["team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"})
        all_wins = pd.concat([wins_a, wins_b]).dropna()
        if not all_wins.empty:
            min_win = all_wins.nsmallest(1, "pts").iloc[0]
            answer3 = str(min_win["owner"])
            wrong3 = [o for o in all_owners if o != answer3][:3]
            opts3 = wrong3 + [answer3]
            random.shuffle(opts3)
            questions.append(TriviaQuestion(
                question=f"Which manager won with the fewest points ever ({min_win['pts']:.1f} pts)?",
                answer=answer3,
                answer_display=answer3,
                category="Scoring",
                difficulty="hard",
                context=f"{answer3} won with just {min_win['pts']:.1f} pts",
                options=opts3,
            ))

    # --- CHAMPIONSHIP QUESTIONS ---
    champs = matchups_df[matchups_df["is_championship"].fillna(False)].copy()
    if not champs.empty:
        champs["champion"] = champs.apply(
            lambda r: r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"], axis=1
        )
        champ_counts = champs["champion"].value_counts()
        top_champ = champ_counts.index[0]
        wrong_champs = [o for o in all_owners if o != top_champ][:3]
        opts_c = wrong_champs + [top_champ]
        random.shuffle(opts_c)
        questions.append(TriviaQuestion(
            question="Who has won the most championships?",
            answer=top_champ,
            answer_display=top_champ,
            category="Championships",
            difficulty="easy",
            context=f"{top_champ} has {champ_counts[top_champ]} championship(s)",
            options=opts_c,
        ))

        # Closest championship
        champs["margin"] = abs(champs["points_a"] - champs["points_b"])
        if champs["margin"].isna().all():
            closest = None
        else:
            closest = champs.nsmallest(1, "margin").iloc[0]
        if closest is not None:
            closest_season = int(closest["season"])
            wrong_seasons = [s for s in seasons if s != closest_season][:3]
            opts_s = [str(s) for s in wrong_seasons] + [str(closest_season)]
            random.shuffle(opts_s)
            questions.append(TriviaQuestion(
                question="Which season had the closest championship game?",
                answer=str(closest_season),
                answer_display=str(closest_season),
                category="Championships",
                difficulty="medium",
                context=f"{closest_season}: margin of {closest['margin']:.2f} pts",
                options=opts_s,
            ))

        # Runner-up most times
        champs["runner_up"] = champs.apply(
            lambda r: r["team_b_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_a_owner"], axis=1
        )
        ru_counts = champs["runner_up"].value_counts()
        if len(ru_counts) > 0:
            top_ru = ru_counts.index[0]
            wrong_ru = [o for o in all_owners if o != top_ru][:3]
            opts_ru = wrong_ru + [top_ru]
            random.shuffle(opts_ru)
            questions.append(TriviaQuestion(
                question="Who has been runner-up the most times without winning?",
                answer=top_ru,
                answer_display=top_ru,
                category="Championships",
                difficulty="medium",
                context=f"{top_ru} has been runner-up {ru_counts[top_ru]} time(s)",
                options=opts_ru,
            ))

    # --- DRAFT QUESTIONS ---
    if not draft_df.empty:
        # Most drafted player
        player_counts = draft_df["player"].value_counts()
        top_player = player_counts.index[0]
        wrong_players = list(player_counts.index[1:4])
        opts_p = wrong_players + [top_player]
        random.shuffle(opts_p)
        questions.append(TriviaQuestion(
            question="Which player has been drafted the most times in league history?",
            answer=top_player,
            answer_display=top_player,
            category="Draft",
            difficulty="medium",
            context=f"{top_player} was drafted {player_counts[top_player]} times",
            options=opts_p,
        ))

        # Most common QB round
        qb_drafts = draft_df[draft_df["position"] == "QB"]
        if not qb_drafts.empty:
            most_common_round = int(qb_drafts["round"].mode()[0])
            other_rounds = [r for r in [1,2,3,4,5,6,7,8,9,10,11,12] if r != most_common_round][:3]
            opts_r = [str(r) for r in other_rounds] + [str(most_common_round)]
            random.shuffle(opts_r)
            questions.append(TriviaQuestion(
                question="Which round do managers most commonly draft their starting QB?",
                answer=str(most_common_round),
                answer_display=f"Round {most_common_round}",
                category="Draft",
                difficulty="medium",
                context=f"Round {most_common_round} is most common for QB selections",
                options=opts_r,
            ))

        # First round busts (players drafted R1 with below-average VORP or no starts)
        r1_picks = draft_df[draft_df["round"] == 1]
        if not r1_picks.empty and not rosters_df.empty:
            r1_starters = rosters_df[rosters_df["player"].isin(r1_picks["player"]) & rosters_df["starter"].fillna(False)]
            if not r1_starters.empty:
                r1_pts = r1_starters.groupby("player")["points"].sum()
                worst_r1 = r1_pts.idxmin()
                best_r1_owners = draft_df[draft_df["player"] == worst_r1]["owner_name"].dropna()
                if not best_r1_owners.empty:
                    bust_owner = best_r1_owners.iloc[0]
                    wrong_busts = [o for o in all_owners if o != bust_owner][:3]
                    opts_b = wrong_busts + [bust_owner]
                    random.shuffle(opts_b)
                    questions.append(TriviaQuestion(
                        question=f"Who drafted the biggest first-round bust ({worst_r1})?",
                        answer=bust_owner,
                        answer_display=bust_owner,
                        category="Draft",
                        difficulty="hard",
                        context=f"{worst_r1} scored only {r1_pts[worst_r1]:.1f} started pts — worst R1 pick",
                        options=opts_b,
                    ))

    # --- RECORDS QUESTIONS ---
    if not all_scores.empty and all_scores["pts"].notna().any():
        # Most career wins
        def _wins_for(owner: str) -> int:
            w_a = matchups_df[(matchups_df["team_a_owner"] == owner) & (matchups_df["winner_team_id"] == matchups_df["team_a_id"])]
            w_b = matchups_df[(matchups_df["team_b_owner"] == owner) & (matchups_df["winner_team_id"] == matchups_df["team_b_id"])]
            return len(w_a) + len(w_b)
        win_counts = {o: _wins_for(o) for o in all_owners}
        most_wins_owner = max(win_counts, key=win_counts.get)
        wrong_w = [o for o in all_owners if o != most_wins_owner][:3]
        opts_w = wrong_w + [most_wins_owner]
        random.shuffle(opts_w)
        questions.append(TriviaQuestion(
            question="Who has the most career wins in league history?",
            answer=most_wins_owner,
            answer_display=most_wins_owner,
            category="Records",
            difficulty="easy",
            context=f"{most_wins_owner} has {win_counts[most_wins_owner]} career wins",
            options=opts_w,
        ))

        # Highest single season points
        season_owner_pts = all_scores.groupby(["season", "owner"])["pts"].sum().reset_index()
        if not season_owner_pts.empty:
            top_season = season_owner_pts.nlargest(1, "pts").iloc[0]
            ts_owner = str(top_season["owner"])
            wrong_ts = [o for o in all_owners if o != ts_owner][:3]
            opts_ts = wrong_ts + [ts_owner]
            random.shuffle(opts_ts)
            questions.append(TriviaQuestion(
                question=f"Who scored the most points in a single season ({int(top_season['season'])})?",
                answer=ts_owner,
                answer_display=ts_owner,
                category="Records",
                difficulty="medium",
                context=f"{ts_owner} scored {top_season['pts']:.1f} pts in {int(top_season['season'])}",
                options=opts_ts,
            ))

    # --- RIVALRY QUESTIONS ---
    if len(all_owners) >= 2:
        # Most frequent matchup pair
        pairs: dict[tuple, int] = {}
        for _, row in matchups_df.iterrows():
            a, b = row["team_a_owner"], row["team_b_owner"]
            if pd.isna(a) or pd.isna(b):
                continue
            key = tuple(sorted([str(a), str(b)]))
            pairs[key] = pairs.get(key, 0) + 1
        if pairs:
            top_pair = max(pairs, key=pairs.get)
            answer_pair = f"{top_pair[0]} vs {top_pair[1]}"
            other_pairs = [f"{all_owners[i]} vs {all_owners[j]}" for i in range(min(3, len(all_owners))) for j in range(i+1, min(4, len(all_owners))) if f"{all_owners[i]} vs {all_owners[j]}" != answer_pair][:3]
            opts_pair = other_pairs + [answer_pair]
            random.shuffle(opts_pair)
            questions.append(TriviaQuestion(
                question="Which two managers have played each other the most?",
                answer=answer_pair,
                answer_display=answer_pair,
                category="Rivalries",
                difficulty="medium",
                context=f"{answer_pair} have met {pairs[top_pair]} times",
                options=opts_pair,
            ))

        # Best single-season H2H dominance
        if not matchups_df.empty:
            h2h: dict[str, dict[str, int]] = {}
            for _, row in matchups_df.iterrows():
                a, b = row.get("team_a_owner"), row.get("team_b_owner")
                wid = row.get("winner_team_id")
                aid, bid = row.get("team_a_id"), row.get("team_b_id")
                if pd.isna(a) or pd.isna(b):
                    continue
                winner = str(a) if wid == aid else str(b)
                loser = str(b) if winner == str(a) else str(a)
                h2h.setdefault(winner, {}).setdefault(loser, 0)
                h2h[winner][loser] += 1
            if h2h:
                best_owner, best_opp, best_wins = "", "", 0
                for owner, opps in h2h.items():
                    for opp, w in opps.items():
                        if w > best_wins:
                            best_wins, best_owner, best_opp = w, owner, opp
                if best_owner:
                    wrong_h2h = [o for o in all_owners if o != best_owner][:3]
                    opts_h2h = wrong_h2h + [best_owner]
                    random.shuffle(opts_h2h)
                    questions.append(TriviaQuestion(
                        question=f"Who has the most wins against a single opponent (vs {best_opp})?",
                        answer=best_owner,
                        answer_display=best_owner,
                        category="Rivalries",
                        difficulty="hard",
                        context=f"{best_owner} is {best_wins}–? vs {best_opp} all-time",
                        options=opts_h2h,
                    ))

    return [q for q in questions if len(q.options) >= 2]


def render(conn) -> None:
    inject_css()
    st.title("🧠 League Trivia")
    st.caption("How well do you know your league's history?")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks").df())

    if matchups_df.empty:
        st.info("No data available for trivia.")
        return

    # Always render the New Game button (never inside `or` short-circuit)
    new_game = st.button("🔀 New Game")

    if "trivia_questions" not in st.session_state or new_game:
        try:
            raw_q = _generate_questions(matchups_df, rosters_df, draft_df)
        except Exception as e:
            st.error(f"Could not generate questions: {e}")
            return
        random.shuffle(raw_q)
        st.session_state["trivia_questions"] = raw_q
        st.session_state["trivia_idx"] = 0
        st.session_state["trivia_score"] = 0
        st.session_state["trivia_answered"] = False
        st.session_state["trivia_selected"] = None

    questions = st.session_state.get("trivia_questions", [])
    if not questions:
        st.warning("Could not generate trivia questions from available data.")
        return

    # Category filter
    all_cats = sorted({q.category for q in questions})
    sel_cat = st.selectbox("Category", ["All Categories"] + all_cats, key="trivia_cat")
    filtered = [q for q in questions if sel_cat == "All Categories" or q.category == sel_cat]
    if not filtered:
        st.info("No questions in this category.")
        return

    idx = st.session_state.get("trivia_idx", 0) % len(filtered)
    q = filtered[idx]

    score = st.session_state.get("trivia_score", 0)
    total_answered = idx

    # Header
    col_score, col_progress = st.columns([1, 3])
    with col_score:
        st.metric("Score", f"{score} / {total_answered}")
    with col_progress:
        st.progress(min(1.0, total_answered / max(len(filtered), 1)))

    st.divider()

    st.markdown(f"### {q.question}")
    st.caption(f"Category: **{q.category}** · Difficulty: **{q.difficulty}**")

    answered = st.session_state.get("trivia_answered", False)

    if not answered:
        selected = st.radio("Choose your answer:", q.options, key=f"trivia_radio_{idx}_{sel_cat}", index=None)
        if st.button("Submit Answer", disabled=(selected is None)):
            st.session_state["trivia_answered"] = True
            st.session_state["trivia_selected"] = selected
            if selected == q.answer:
                st.session_state["trivia_score"] = score + 1
            st.rerun()
    else:
        selected = st.session_state.get("trivia_selected")
        correct = selected == q.answer

        for opt in q.options:
            if opt == q.answer:
                st.success(f"✅ {opt}")
            elif opt == selected and not correct:
                st.error(f"❌ {opt} (your answer)")
            else:
                st.write(f"○ {opt}")

        if correct:
            st.success("Correct! 🎉")
        else:
            st.error(f"Wrong. The answer is **{q.answer_display}**.")

        st.info(f"📊 Context: {q.context}")

        if st.button("Next Question ➡️"):
            st.session_state["trivia_idx"] = (idx + 1) % len(filtered)
            st.session_state["trivia_answered"] = False
            st.session_state["trivia_selected"] = None
            st.rerun()
