"""Expected wins and schedule luck metrics."""

from __future__ import annotations

import pandas as pd
import numpy as np

from fantasy.analytics.standings import _filter_league, _regular_season, season_standings


def expected_wins(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Compute expected wins for each team in a season based on all-play.

    For each week, expected wins = number of other teams outscored / (N - 1).
    Summed across the regular season, this gives schedule-independent
    expected wins.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame from load_export.
        season (int): The season year.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        DataFrame with columns: team_id, owner, team, expected_wins,
        sorted by expected_wins desc.
    """
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return pd.DataFrame()

    weekly_scores: dict[int, dict[str, tuple[str, str, float]]] = {}
    for _, row in df.iterrows():
        week = int(row["week"]) if pd.notna(row["week"]) else -1
        if week not in weekly_scores:
            weekly_scores[week] = {}
        weekly_scores[week][row["team_a_id"]] = (row["team_a_owner"], row["team_a_name"], row["points_a"] or 0.0)
        weekly_scores[week][row["team_b_id"]] = (row["team_b_owner"], row["team_b_name"], row["points_b"] or 0.0)

    exp: dict[str, dict] = {}
    for week, teams in weekly_scores.items():
        scores = list(teams.items())
        n = len(scores)
        if n <= 1:
            continue
        for team_id, (owner, team_name, pts) in scores:
            if team_id not in exp:
                exp[team_id] = {"owner": owner, "team": team_name, "expected_wins": 0.0}
            beaten = sum(1 for oid, (_, _, opts) in scores if oid != team_id and pts > opts)
            tied = sum(1 for oid, (_, _, opts) in scores if oid != team_id and pts == opts)
            exp[team_id]["expected_wins"] += (beaten + 0.5 * tied) / (n - 1)

    out = pd.DataFrame.from_dict(exp, orient="index").reset_index(names="team_id")
    return out.sort_values("expected_wins", ascending=False).reset_index(drop=True)


def luck_metrics(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Compute luck metrics comparing actual wins to expected wins.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame from load_export.
        season (int): The season year.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        DataFrame with columns: owner, team, actual_wins, expected_wins,
        luck_delta, schedule_difficulty, sorted by luck_delta desc.
        luck_delta = actual_wins - expected_wins (positive = lucky).
        schedule_difficulty = average opponent points per game.
    """
    actual = season_standings(matchups_df, season, league_id)
    exp = expected_wins(matchups_df, season, league_id)
    if actual.empty or exp.empty:
        return pd.DataFrame()

    merged = actual.merge(exp[["team_id", "expected_wins"]], on="team_id", how="left")
    merged["luck_delta"] = merged["h2h_wins"] - merged["expected_wins"]

    # Schedule difficulty: avg opponent points
    df = _regular_season(matchups_df, season, league_id)
    opp_pts: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        pa, pb = row["points_a"] or 0.0, row["points_b"] or 0.0
        opp_pts.setdefault(row["team_a_id"], []).append(pb)
        opp_pts.setdefault(row["team_b_id"], []).append(pa)

    sched_diff = {tid: sum(pts) / len(pts) for tid, pts in opp_pts.items() if pts}
    merged["schedule_difficulty"] = merged["team_id"].map(sched_diff)

    cols = ["owner", "team", "h2h_wins", "expected_wins", "luck_delta", "schedule_difficulty"]
    return merged[cols].rename(columns={"h2h_wins": "actual_wins"}).sort_values("luck_delta", ascending=False).reset_index(drop=True)


def schedule_luck(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Schedule-focused luck: opponent quality and weekly scoring luck.

    Returns per-owner:
    - actual_wins, expected_wins, luck_delta
    - opp_avg_pf: avg score your opponents posted against you
    - opp_season_avg_pf: opponents' avg score across all their games (true opponent quality)
    - opp_above_avg: opp_avg_pf minus opp_season_avg_pf (positive = faced hot opponents = unlucky)
    - opp_win_pct: avg win% of opponents you faced (record-based SOS)
    """
    base = luck_metrics(matchups_df, season, league_id)
    if base.empty:
        return pd.DataFrame()

    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return base

    # Build per-team season avg PF and win records
    all_standings = season_standings(matchups_df, season, league_id)
    team_season_avg: dict[str, float] = {}
    team_win_pct: dict[str, float] = {}
    if not all_standings.empty:
        for _, row in all_standings.iterrows():
            tid = row.get("team_id")
            if tid:
                total_games = (row.get("h2h_wins", 0) or 0) + (row.get("h2h_losses", 0) or 0) + (row.get("h2h_ties", 0) or 0)
                team_win_pct[tid] = float(row.get("h2h_wins", 0) or 0) / total_games if total_games > 0 else 0.0

    # Season avg PF from matchup data
    team_all_scores: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        pa, pb = float(row["points_a"] or 0), float(row["points_b"] or 0)
        team_all_scores.setdefault(row["team_a_id"], []).append(pa)
        team_all_scores.setdefault(row["team_b_id"], []).append(pb)
    for tid, scores in team_all_scores.items():
        team_season_avg[tid] = float(np.mean(scores)) if scores else 0.0

    # Per-owner: aggregate opponent quality stats
    owner_opp_scores: dict[str, list[float]] = {}       # opp score against you each week
    owner_opp_season_avgs: dict[str, list[float]] = {}  # opp season avg
    owner_opp_win_pcts: dict[str, list[float]] = {}     # opp win%

    owner_map: dict[str, str] = {}  # team_id → owner
    for _, row in df.iterrows():
        owner_map[row["team_a_id"]] = row["team_a_owner"]
        owner_map[row["team_b_id"]] = row["team_b_owner"]

    for _, row in df.iterrows():
        pa, pb = float(row["points_a"] or 0), float(row["points_b"] or 0)
        a_owner = row["team_a_owner"]
        b_owner = row["team_b_owner"]
        aid, bid = row["team_a_id"], row["team_b_id"]

        # team_a faced team_b as opponent
        owner_opp_scores.setdefault(a_owner, []).append(pb)
        owner_opp_season_avgs.setdefault(a_owner, []).append(team_season_avg.get(bid, pb))
        owner_opp_win_pcts.setdefault(a_owner, []).append(team_win_pct.get(bid, 0.0))

        # team_b faced team_a as opponent
        owner_opp_scores.setdefault(b_owner, []).append(pa)
        owner_opp_season_avgs.setdefault(b_owner, []).append(team_season_avg.get(aid, pa))
        owner_opp_win_pcts.setdefault(b_owner, []).append(team_win_pct.get(aid, 0.0))

    opp_avg = {o: float(np.mean(v)) for o, v in owner_opp_scores.items()}
    opp_season_avg = {o: float(np.mean(v)) for o, v in owner_opp_season_avgs.items()}
    opp_win_pct = {o: float(np.mean(v)) for o, v in owner_opp_win_pcts.items()}

    out = base.copy()
    out["opp_avg_pf"] = out["owner"].map(opp_avg)
    out["opp_season_avg_pf"] = out["owner"].map(opp_season_avg)
    out["opp_above_avg"] = (out["opp_avg_pf"] - out["opp_season_avg_pf"]).round(2)
    out["opp_win_pct"] = out["owner"].map(opp_win_pct)
    return out.sort_values("opp_above_avg", ascending=False).reset_index(drop=True)
