"""Expected wins and schedule luck metrics."""

from __future__ import annotations

import pandas as pd

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
    merged["luck_delta"] = merged["wins"] - merged["expected_wins"]

    # Schedule difficulty: avg opponent points
    df = _regular_season(matchups_df, season, league_id)
    opp_pts: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        pa, pb = row["points_a"] or 0.0, row["points_b"] or 0.0
        opp_pts.setdefault(row["team_a_id"], []).append(pb)
        opp_pts.setdefault(row["team_b_id"], []).append(pa)

    sched_diff = {tid: sum(pts) / len(pts) for tid, pts in opp_pts.items() if pts}
    merged["schedule_difficulty"] = merged["team_id"].map(sched_diff)

    cols = ["owner", "team", "wins", "expected_wins", "luck_delta", "schedule_difficulty"]
    return merged[cols].rename(columns={"wins": "actual_wins"}).sort_values("luck_delta", ascending=False).reset_index(drop=True)
