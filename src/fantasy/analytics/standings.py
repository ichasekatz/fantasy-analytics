"""Season standings and all-play record calculations.

Median scoring note
-------------------
Sleeper seasons (2024+) use a median matchup rule: each week a team also wins
or loses a "median game" based on whether their score beats the weekly league
median. This doubles the game count relative to ESPN seasons, so raw win totals
are not comparable across platforms.

For cross-season comparisons always use ``h2h_win_pct`` (head-to-head only).
``total_wins`` and ``total_win_pct`` include median wins for within-season use.
"""

from __future__ import annotations

import pandas as pd

# Seasons that use the median matchup rule (doubles game count)
_median_seasons: frozenset[int] = frozenset({2024, 2025, 2026})


def _filter_league(matchups_df: pd.DataFrame, league_id: str | None) -> pd.DataFrame:
    """Filter matchups to a specific league if league_id is provided.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        Filtered (or unfiltered) copy of the DataFrame.
    """
    if league_id is None or "league_id" not in matchups_df.columns:
        return matchups_df
    return matchups_df[matchups_df["league_id"] == league_id].copy()


def _regular_season(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Return regular-season matchups only (excludes playoff/consolation/championship).

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame.
        season (int): The season year.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        Filtered DataFrame of regular-season matchups.
    """
    df = _filter_league(matchups_df, league_id)
    mask = (
        (df["season"] == season)
        & (~df["is_playoff"])
        & (~df["is_consolation"])
        & (~df["is_championship"])
    )
    return df[mask].copy()


def _median_wins(df: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """Compute median wins/losses for each team from weekly scores.

    For each week, any team scoring strictly above the weekly median gets a
    median win; below gets a median loss; ties with the median count as a loss
    (standard Sleeper behaviour).

    Args:
        df (pd.DataFrame): Regular-season matchups for one season.

    Returns:
        Dict mapping team_id → (median_wins, median_losses).
    """
    weekly: dict[int, dict[str, float]] = {}
    for _, row in df.iterrows():
        week = int(row["week"])
        weekly.setdefault(week, {})[row["team_a_id"]] = row["points_a"] or 0.0
        weekly.setdefault(week, {})[row["team_b_id"]] = row["points_b"] or 0.0

    result: dict[str, tuple[int, int]] = {}
    for week, scores in weekly.items():
        pts_list = list(scores.values())
        n = len(pts_list)
        # Sleeper median: middle value for even n is average of two middle scores
        sorted_pts = sorted(pts_list)
        if n % 2 == 1:
            median = sorted_pts[n // 2]
        else:
            median = (sorted_pts[n // 2 - 1] + sorted_pts[n // 2]) / 2.0
        for tid, pts in scores.items():
            mw, ml = result.get(tid, (0, 0))
            if pts > median:
                result[tid] = (mw + 1, ml)
            else:
                result[tid] = (mw, ml + 1)
    return result


def season_standings(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Compute regular-season standings for a given season.

    For Sleeper seasons (2024+) with the median matchup rule, the returned
    DataFrame includes both head-to-head and median win columns.
    Use ``h2h_win_pct`` for cross-season comparisons; ``total_win_pct`` for
    within-season ranking in Sleeper leagues.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame from load_export.
        season (int): The season year (e.g. 2023).
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        DataFrame sorted by total_wins desc then PF desc, with columns:
        owner, team, h2h_wins, h2h_losses, h2h_ties, h2h_win_pct,
        median_wins, median_losses, total_wins, total_losses, total_win_pct,
        points_for, points_against, avg_pf, has_median.
    """
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return pd.DataFrame()

    has_median = season in _median_seasons
    records: dict[str, dict] = {}

    def _ensure(team_id: str, owner: str, team: str) -> None:
        if team_id not in records:
            records[team_id] = {
                "owner": owner, "team": team,
                "h2h_wins": 0, "h2h_losses": 0, "h2h_ties": 0,
                "pf": 0.0, "pa": 0.0,
            }

    for _, row in df.iterrows():
        a_id, b_id = row["team_a_id"], row["team_b_id"]
        pa, pb = row["points_a"] or 0.0, row["points_b"] or 0.0
        _ensure(a_id, row["team_a_owner"], row["team_a_name"])
        _ensure(b_id, row["team_b_owner"], row["team_b_name"])
        records[a_id]["pf"] += pa
        records[a_id]["pa"] += pb
        records[b_id]["pf"] += pb
        records[b_id]["pa"] += pa
        if row["winner_team_id"] == a_id:
            records[a_id]["h2h_wins"] += 1
            records[b_id]["h2h_losses"] += 1
        elif row["winner_team_id"] == b_id:
            records[b_id]["h2h_wins"] += 1
            records[a_id]["h2h_losses"] += 1
        else:
            records[a_id]["h2h_ties"] += 1
            records[b_id]["h2h_ties"] += 1

    # Compute median wins for Sleeper seasons
    med = _median_wins(df) if has_median else {}

    out = pd.DataFrame.from_dict(records, orient="index").reset_index(names="team_id")
    out["median_wins"] = out["team_id"].map(lambda t: med.get(t, (0, 0))[0])
    out["median_losses"] = out["team_id"].map(lambda t: med.get(t, (0, 0))[1])
    out["total_wins"] = out["h2h_wins"] + out["median_wins"]
    out["total_losses"] = out["h2h_losses"] + out["median_losses"]
    out["total_ties"] = out["h2h_ties"]

    h2h_games = out["h2h_wins"] + out["h2h_losses"] + out["h2h_ties"]
    total_games = out["total_wins"] + out["total_losses"] + out["total_ties"]
    out["h2h_win_pct"] = (out["h2h_wins"] + 0.5 * out["h2h_ties"]) / h2h_games.replace(0, float("nan"))
    out["total_win_pct"] = (out["total_wins"] + 0.5 * out["total_ties"]) / total_games.replace(0, float("nan"))
    out["avg_pf"] = out["pf"] / h2h_games.replace(0, float("nan"))
    out["has_median"] = has_median
    out = out.rename(columns={"pf": "points_for", "pa": "points_against"})
    return out.sort_values(["total_wins", "points_for"], ascending=False).reset_index(drop=True)


def all_play_records(matchups_df: pd.DataFrame, season: int, league_id: str | None = None) -> pd.DataFrame:
    """Compute all-play W-L records for a season.

    For every week, counts how many other teams each team would have beaten.
    Provides a schedule-independent measure of team strength.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame from load_export.
        season (int): The season year.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        DataFrame with columns: team_id, owner, team, ap_wins, ap_losses,
        ap_ties, ap_win_pct, sorted by ap_win_pct desc.
    """
    df = _regular_season(matchups_df, season, league_id)
    if df.empty:
        return pd.DataFrame()

    weekly_scores: dict[int, dict[str, tuple[str, str, float]]] = {}
    for _, row in df.iterrows():
        week = row["week"]
        if week not in weekly_scores:
            weekly_scores[week] = {}
        weekly_scores[week][row["team_a_id"]] = (row["team_a_owner"], row["team_a_name"], row["points_a"] or 0.0)
        weekly_scores[week][row["team_b_id"]] = (row["team_b_owner"], row["team_b_name"], row["points_b"] or 0.0)

    ap: dict[str, dict] = {}
    for week, teams in weekly_scores.items():
        scores = list(teams.items())
        for team_id, (owner, team_name, pts) in scores:
            if team_id not in ap:
                ap[team_id] = {"owner": owner, "team": team_name, "ap_wins": 0, "ap_losses": 0, "ap_ties": 0}
            for other_id, (_, _, other_pts) in scores:
                if other_id == team_id:
                    continue
                if pts > other_pts:
                    ap[team_id]["ap_wins"] += 1
                elif pts < other_pts:
                    ap[team_id]["ap_losses"] += 1
                else:
                    ap[team_id]["ap_ties"] += 1

    out = pd.DataFrame.from_dict(ap, orient="index").reset_index(names="team_id")
    total = out["ap_wins"] + out["ap_losses"] + out["ap_ties"]
    out["ap_win_pct"] = (out["ap_wins"] + 0.5 * out["ap_ties"]) / total.replace(0, float("nan"))
    return out.sort_values("ap_win_pct", ascending=False).reset_index(drop=True)


def career_standings(matchups_df: pd.DataFrame, league_id: str | None = None) -> pd.DataFrame:
    """Aggregate career regular-season standings across all seasons.

    Uses head-to-head wins and win% as the primary comparable metric so that
    Sleeper seasons (which add median games) do not inflate win totals relative
    to ESPN seasons. Median wins are summed separately for reference.

    Args:
        matchups_df (pd.DataFrame): Full matchups DataFrame from load_export.
        league_id (str | None): League to filter to, or None for all leagues.

    Returns:
        DataFrame with columns: owner, h2h_wins, h2h_losses, h2h_ties,
        h2h_win_pct (primary cross-season metric), median_wins, median_losses,
        total_wins, points_for, points_against, seasons_played, avg_pf,
        sorted by h2h_win_pct desc.
    """
    df = _filter_league(matchups_df, league_id)
    seasons = df["season"].unique()
    season_dfs = [season_standings(df, int(s), league_id) for s in seasons]
    season_dfs = [d for d in season_dfs if not d.empty]
    if not season_dfs:
        return pd.DataFrame()

    combined = pd.concat(season_dfs, ignore_index=True)
    grouped = (
        combined.groupby("owner")
        .agg(
            h2h_wins=("h2h_wins", "sum"),
            h2h_losses=("h2h_losses", "sum"),
            h2h_ties=("h2h_ties", "sum"),
            median_wins=("median_wins", "sum"),
            median_losses=("median_losses", "sum"),
            total_wins=("total_wins", "sum"),
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
            seasons_played=("owner", "count"),
        )
        .reset_index()
    )
    h2h_games = grouped["h2h_wins"] + grouped["h2h_losses"] + grouped["h2h_ties"]
    grouped["h2h_win_pct"] = (grouped["h2h_wins"] + 0.5 * grouped["h2h_ties"]) / h2h_games.replace(0, float("nan"))
    grouped["avg_pf"] = grouped["points_for"] / h2h_games.replace(0, float("nan"))
    return grouped.sort_values("h2h_win_pct", ascending=False).reset_index(drop=True)
