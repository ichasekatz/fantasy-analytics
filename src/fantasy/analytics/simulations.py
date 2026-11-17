"""Schedule simulation and Monte Carlo luck analysis."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd


def _regular_season(
    matchups_df: pd.DataFrame,
    season: int,
    league_id: str | None,
) -> pd.DataFrame:
    """Return regular-season matchups for the given season and league.

    Args:
        matchups_df: Full matchups DataFrame.
        season: Season to filter to.
        league_id: League to filter to, or None.

    Returns:
        Filtered copy with only regular-season rows.
    """
    df = matchups_df[matchups_df["season"] == season].copy()
    if league_id is not None:
        df = df[df["league_id"] == league_id]
    if "is_playoff" in df.columns:
        df = df[~df["is_playoff"].fillna(False)]
    return df


def _team_weekly_scores(df: pd.DataFrame) -> dict[str, dict[int, float]]:
    """Build mapping owner → {week → points} from matchup rows.

    Args:
        df: Regular-season matchups DataFrame.

    Returns:
        Nested dict: owner_name → week → score.
    """
    scores: dict[str, dict[int, float]] = {}
    for _, row in df.iterrows():
        owner_a: str = row["team_a_owner"]
        owner_b: str = row["team_b_owner"]
        week: int = int(row["week"])
        scores.setdefault(owner_a, {})[week] = float(row["points_a"])
        scores.setdefault(owner_b, {})[week] = float(row["points_b"])
    return scores


def _weekly_matchups(df: pd.DataFrame) -> dict[int, list[tuple[str, str]]]:
    """Build mapping week → list of (owner_a, owner_b) matchup pairs.

    Args:
        df: Regular-season matchups DataFrame.

    Returns:
        Dict: week → [(owner_a, owner_b), ...].
    """
    pairs: dict[int, list[tuple[str, str]]] = {}
    for _, row in df.iterrows():
        week = int(row["week"])
        pairs.setdefault(week, []).append((row["team_a_owner"], row["team_b_owner"]))
    return pairs


def _infer_playoff_cutoff(matchups_df: pd.DataFrame, season: int) -> int:
    """Infer number of playoff teams from matchup flags.

    Counts distinct team IDs appearing in playoff matchups.

    Args:
        matchups_df: Full matchups DataFrame.
        season: Season to check.

    Returns:
        Number of playoff teams (defaults to 4 if none found).
    """
    playoff_rows = matchups_df[
        (matchups_df["season"] == season) & matchups_df["is_playoff"].fillna(False)
    ]
    if playoff_rows.empty:
        return 4  # reasonable default
    ids = set(playoff_rows["team_a_id"].tolist()) | set(playoff_rows["team_b_id"].tolist())
    return len(ids)


def schedule_swap_wins(
    matchups_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Deterministic schedule swap simulation.

    For each team A, counts how many wins they would have accumulated if they
    had faced the same opponents B faced each week (keeping A's actual scores).
    Runs for every other team B in the league.

    Args:
        matchups_df: Matchups DataFrame.
        season: Season to simulate.
        league_id: Filter to league, or None.

    Returns:
        DataFrame with columns: owner, actual_wins, min_wins, max_wins,
        avg_simulated_wins, wins_distribution, schedule_luck_rank.
        Returns empty DataFrame if fewer than 2 teams found.
    """
    empty = pd.DataFrame(
        columns=["owner", "actual_wins", "min_wins", "max_wins",
                 "avg_simulated_wins", "wins_distribution", "schedule_luck_rank"]
    )
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return empty

    scores = _team_weekly_scores(df)
    weekly_pairs = _weekly_matchups(df)
    owners = list(scores.keys())
    if len(owners) < 2:
        return empty

    # Actual wins: count from matchup data
    actual_wins: dict[str, int] = {o: 0 for o in owners}
    for week, pairs in weekly_pairs.items():
        for oa, ob in pairs:
            sa = scores.get(oa, {}).get(week, 0.0)
            sb = scores.get(ob, {}).get(week, 0.0)
            if sa > sb:
                actual_wins[oa] = actual_wins.get(oa, 0) + 1
            elif sb > sa:
                actual_wins[ob] = actual_wins.get(ob, 0) + 1

    # For each owner A, simulate with each other owner B's schedule
    # B's schedule = set of weekly opponents B faced
    owner_schedules: dict[str, dict[int, str]] = {o: {} for o in owners}
    for week, pairs in weekly_pairs.items():
        for oa, ob in pairs:
            owner_schedules[oa][week] = ob
            owner_schedules[ob][week] = oa

    sim_wins_all: dict[str, list[int]] = {o: [] for o in owners}
    for owner_a in owners:
        for owner_b in owners:
            if owner_a == owner_b:
                continue
            # Give owner_a the opponents owner_b faced
            w = 0
            for week, opp_of_b in owner_schedules.get(owner_b, {}).items():
                # owner_a's score that week vs the opponent owner_b faced
                score_a = scores.get(owner_a, {}).get(week, 0.0)
                score_opp = scores.get(opp_of_b, {}).get(week, 0.0)
                if score_a > score_opp:
                    w += 1
            sim_wins_all[owner_a].append(w)

    rows = []
    for owner in owners:
        sim = sim_wins_all[owner]
        rows.append({
            "owner": owner,
            "actual_wins": actual_wins.get(owner, 0),
            "min_wins": int(np.min(sim)) if sim else 0,
            "max_wins": int(np.max(sim)) if sim else 0,
            "avg_simulated_wins": float(np.mean(sim)) if sim else 0.0,
            "wins_distribution": json.dumps(sorted(sim)),
        })

    result = pd.DataFrame(rows)
    result["schedule_luck_rank"] = result["avg_simulated_wins"].rank(ascending=False).astype(int)
    return result.sort_values("avg_simulated_wins", ascending=False).reset_index(drop=True)


def monte_carlo_standings(
    matchups_df: pd.DataFrame,
    season: int,
    n_sims: int = 1000,
    league_id: str | None = None,
    through_week: int | None = None,
) -> pd.DataFrame:
    """Monte Carlo playoff probability, optionally as-of a specific week.

    When through_week is None (default): randomises the full schedule using
    actual scores — equivalent to "alternate universe" luck analysis.

    When through_week is set: locks actual results for weeks 1..through_week,
    then for remaining weeks draws each team's score from their observed scoring
    distribution and simulates random matchups. This gives "playoff odds at
    week N" without knowing what actually happened later.

    Args:
        matchups_df: Matchups DataFrame.
        season: Season to simulate.
        n_sims: Number of Monte Carlo iterations.
        league_id: Filter to league, or None.
        through_week: If set, only commit results through this week and
            simulate the rest. Use None for full-season analysis.

    Returns:
        DataFrame with columns: owner, actual_wins, mean_simulated_wins,
        p10_wins, p25_wins, p50_wins, p75_wins, p90_wins, playoff_probability.
        Returns empty DataFrame if fewer than 2 teams found.
    """
    empty = pd.DataFrame(
        columns=["owner", "actual_wins", "mean_simulated_wins",
                 "p10_wins", "p25_wins", "p50_wins", "p75_wins", "p90_wins",
                 "playoff_probability"]
    )
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return empty

    scores = _team_weekly_scores(df)
    owners = list(scores.keys())
    n_teams = len(owners)
    if n_teams < 2:
        return empty

    all_weeks = sorted({w for s in scores.values() for w in s})
    playoff_cutoff = _infer_playoff_cutoff(matchups_df, season)
    rng = np.random.default_rng()

    # Split into locked (past) and open (future to simulate) weeks
    if through_week is not None:
        locked_weeks = [w for w in all_weeks if w <= through_week]
        future_weeks = [w for w in all_weeks if w > through_week]
    else:
        locked_weeks = []
        future_weeks = all_weeks

    # Actual wins through locked weeks (from real matchup pairings)
    weekly_pairs = _weekly_matchups(df)
    actual_wins: dict[str, int] = {o: 0 for o in owners}
    locked_wins: dict[str, int] = {o: 0 for o in owners}
    for week, pairs in weekly_pairs.items():
        for oa, ob in pairs:
            sa = scores.get(oa, {}).get(week, 0.0)
            sb = scores.get(ob, {}).get(week, 0.0)
            if sa > sb:
                actual_wins[oa] = actual_wins.get(oa, 0) + 1
                if week in locked_weeks:
                    locked_wins[oa] = locked_wins.get(oa, 0) + 1
            elif sb > sa:
                actual_wins[ob] = actual_wins.get(ob, 0) + 1
                if week in locked_weeks:
                    locked_wins[ob] = locked_wins.get(ob, 0) + 1

    # Build per-team score distributions for future-week sampling
    # Use all available scores (not just locked) as the distribution basis
    score_arrays: dict[str, np.ndarray] = {}
    for o in owners:
        vals = [v for v in scores.get(o, {}).values() if v > 0]
        score_arrays[o] = np.array(vals, dtype=float) if vals else np.array([100.0])

    sim_win_counts: dict[str, list[int]] = {o: [] for o in owners}
    sim_playoff_counts: dict[str, int] = {o: 0 for o in owners}

    for _ in range(n_sims):
        sim_wins: dict[str, int] = {o: locked_wins[o] for o in owners}

        # Simulate future weeks: sample scores + random pairings
        for week in future_weeks:
            week_scores = [(o, float(rng.choice(score_arrays[o]))) for o in owners]
            shuffled = rng.permutation(len(owners))
            for i in range(0, len(shuffled) - 1, 2):
                ia, ib = int(shuffled[i]), int(shuffled[i + 1])
                oa, sa = week_scores[ia]
                ob, sb = week_scores[ib]
                if sa > sb:
                    sim_wins[oa] += 1
                elif sb > sa:
                    sim_wins[ob] += 1

        # For full-season alternate-universe mode, also randomise locked weeks
        if through_week is None:
            for week in all_weeks:
                week_scores = [(o, scores.get(o, {}).get(week, 0.0)) for o in owners]
                shuffled = rng.permutation(len(owners))
                for i in range(0, len(shuffled) - 1, 2):
                    ia, ib = int(shuffled[i]), int(shuffled[i + 1])
                    oa, sa = week_scores[ia]
                    ob, sb = week_scores[ib]
                    if sa > sb:
                        sim_wins[oa] += 1
                    elif sb > sa:
                        sim_wins[ob] += 1

        for o in owners:
            sim_win_counts[o].append(sim_wins[o])

        sorted_owners = sorted(owners, key=lambda o: sim_wins[o], reverse=True)
        for o in sorted_owners[:playoff_cutoff]:
            sim_playoff_counts[o] += 1

    rows = []
    for owner in owners:
        arr = np.array(sim_win_counts[owner], dtype=float)
        rows.append({
            "owner": owner,
            "actual_wins": actual_wins.get(owner, 0),
            "mean_simulated_wins": float(np.mean(arr)),
            "p10_wins": float(np.percentile(arr, 10)),
            "p25_wins": float(np.percentile(arr, 25)),
            "p50_wins": float(np.percentile(arr, 50)),
            "p75_wins": float(np.percentile(arr, 75)),
            "p90_wins": float(np.percentile(arr, 90)),
            "playoff_probability": sim_playoff_counts[owner] / n_sims,
        })
    return pd.DataFrame(rows).sort_values("mean_simulated_wins", ascending=False).reset_index(drop=True)


def luck_awards(
    matchups_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> dict[str, str]:
    """Named luck awards for a season based on expected vs actual wins.

    Uses the all-play expected-wins method: each week, expected wins =
    fraction of other teams outscored.

    Args:
        matchups_df: Matchups DataFrame.
        season: Season to evaluate.
        league_id: Filter to league, or None.

    Returns:
        Dict with keys: luckiest_manager, unluckiest_manager,
        luckiest_matchup, unluckiest_matchup,
        best_team_missed_playoffs, worst_team_made_playoffs.
        Empty strings for awards that cannot be determined.
    """
    awards: dict[str, str] = {
        "luckiest_manager": "",
        "unluckiest_manager": "",
        "luckiest_matchup": "",
        "unluckiest_matchup": "",
        "best_team_missed_playoffs": "",
        "worst_team_made_playoffs": "",
    }
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return awards

    scores = _team_weekly_scores(df)
    owners = list(scores.keys())
    weeks = sorted({w for s in scores.values() for w in s})
    n_teams = len(owners)
    if n_teams < 2:
        return awards

    # Expected wins via all-play
    expected: dict[str, float] = {o: 0.0 for o in owners}
    actual_w: dict[str, int] = {o: 0 for o in owners}
    weekly_pairs = _weekly_matchups(df)

    for week in weeks:
        week_scores = [(o, scores.get(o, {}).get(week, 0.0)) for o in owners]
        for o, s in week_scores:
            beaten = sum(1 for other_o, other_s in week_scores if other_o != o and s > other_s)
            expected[o] += beaten / (n_teams - 1)

    for week, pairs in weekly_pairs.items():
        for oa, ob in pairs:
            sa = scores.get(oa, {}).get(week, 0.0)
            sb = scores.get(ob, {}).get(week, 0.0)
            if sa > sb:
                actual_w[oa] += 1
            elif sb > sa:
                actual_w[ob] += 1

    luck_delta = {o: actual_w[o] - expected[o] for o in owners}
    awards["luckiest_manager"] = max(luck_delta, key=luck_delta.__getitem__)
    awards["unluckiest_manager"] = min(luck_delta, key=luck_delta.__getitem__)

    # Luckiest/unluckiest individual matchup: biggest upset (loser outscored winner)
    all_matchups = matchups_df[
        (matchups_df["season"] == season) & ~matchups_df["is_playoff"].fillna(False)
    ]
    if league_id:
        all_matchups = all_matchups[all_matchups["league_id"] == league_id]

    if not all_matchups.empty:
        all_matchups = all_matchups.copy()
        all_matchups["upset_margin"] = (all_matchups["points_a"] - all_matchups["points_b"]).abs()
        worst = all_matchups.loc[all_matchups["upset_margin"].idxmax()]
        loser = worst["team_a_owner"] if worst["points_a"] < worst["points_b"] else worst["team_b_owner"]
        winner = worst["team_b_owner"] if loser == worst["team_a_owner"] else worst["team_a_owner"]
        awards["luckiest_matchup"] = f"{winner} def {loser} wk{int(worst['week'])}"
        awards["unluckiest_matchup"] = f"{loser} lost to {winner} wk{int(worst['week'])}"

    # Best team to miss playoffs / worst team to make playoffs
    playoff_rows = matchups_df[(matchups_df["season"] == season) & matchups_df["is_playoff"].fillna(False)]
    if not playoff_rows.empty:
        playoff_owners = set(playoff_rows["team_a_owner"].tolist()) | set(playoff_rows["team_b_owner"].tolist())
        missed = [o for o in owners if o not in playoff_owners]
        made = [o for o in owners if o in playoff_owners]
        if missed:
            awards["best_team_missed_playoffs"] = max(missed, key=lambda o: scores.get(o, {}).values().__iter__().__next__() if scores.get(o) else 0)
            # Better: use total points
            awards["best_team_missed_playoffs"] = max(
                missed, key=lambda o: sum(scores.get(o, {}).values())
            )
        if made:
            awards["worst_team_made_playoffs"] = min(
                made, key=lambda o: sum(scores.get(o, {}).values())
            )

    return awards
