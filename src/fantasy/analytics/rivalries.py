"""Head-to-head rivalry analytics between fantasy managers."""

from __future__ import annotations

import pandas as pd


def _normalize_matchups(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per team-game with owner, opponent, pts_for, pts_against, won, is_playoff, season, week.

    Args:
        matchups_df: Raw matchups DataFrame.

    Returns:
        Normalized per-team DataFrame.
    """
    reg = matchups_df.dropna(subset=["points_a", "points_b"]).copy()

    side_a = reg[["league_id", "season", "week", "team_a_owner", "team_b_owner",
                  "points_a", "points_b", "winner_team_id", "team_a_id",
                  "is_playoff", "is_consolation", "is_championship"]].copy()
    side_a = side_a.rename(columns={
        "team_a_owner": "owner", "team_b_owner": "opponent",
        "points_a": "pf", "points_b": "pa", "team_a_id": "team_id",
    })
    side_a["won"] = side_a["team_id"] == side_a["winner_team_id"]

    side_b = reg[["league_id", "season", "week", "team_b_owner", "team_a_owner",
                  "points_b", "points_a", "winner_team_id", "team_b_id",
                  "is_playoff", "is_consolation", "is_championship"]].copy()
    side_b = side_b.rename(columns={
        "team_b_owner": "owner", "team_a_owner": "opponent",
        "points_b": "pf", "points_a": "pa", "team_b_id": "team_id",
    })
    side_b["won"] = side_b["team_id"] == side_b["winner_team_id"]

    combined = pd.concat([side_a, side_b], ignore_index=True)
    combined = combined.dropna(subset=["owner", "opponent"])
    return combined


def _filter_league(df: pd.DataFrame, league_id: str | None) -> pd.DataFrame:
    if league_id and "league_id" in df.columns:
        return df[df["league_id"] == league_id].copy()
    return df


def _streak(results: list[bool], owner_won: bool) -> int:
    """Current streak length for the given outcome."""
    count = 0
    for r in reversed(results):
        if r == owner_won:
            count += 1
        else:
            break
    return count


def _max_streak(results: list[bool], target: bool) -> int:
    max_s = cur = 0
    for r in results:
        if r == target:
            cur += 1
            max_s = max(max_s, cur)
        else:
            cur = 0
    return max_s


def rivalry_stats(
    matchups_df: pd.DataFrame,
    owner_a: str,
    owner_b: str,
    league_id: str | None = None,
) -> dict:
    """Full rivalry stats between two managers.

    Args:
        matchups_df: Full matchups DataFrame.
        owner_a: First manager name.
        owner_b: Second manager name.
        league_id: Optional league filter.

    Returns:
        Dict with rivalry statistics.
    """
    df = _filter_league(matchups_df, league_id)
    mask = (
        ((df["team_a_owner"] == owner_a) & (df["team_b_owner"] == owner_b)) |
        ((df["team_a_owner"] == owner_b) & (df["team_b_owner"] == owner_a))
    )
    meetings_raw = df[mask].dropna(subset=["points_a", "points_b"]).sort_values(["season", "week"])

    if meetings_raw.empty:
        return {"meetings": [], "all_time_record": (0, 0, 0)}

    meetings = []
    a_wins = a_losses = ties = 0
    reg_a_wins = reg_a_losses = reg_ties = 0
    playoff_a_wins = playoff_a_losses = 0
    champ_meetings: list[dict] = []
    total_pf_a = total_pf_b = 0.0
    margins = []

    a_results: list[bool] = []

    for _, row in meetings_raw.iterrows():
        if row["team_a_owner"] == owner_a:
            pts_a, pts_b = row["points_a"], row["points_b"]
            winner_is_a = row["winner_team_id"] == row["team_a_id"]
        else:
            pts_a, pts_b = row["points_b"], row["points_a"]
            winner_is_a = row["winner_team_id"] == row["team_b_id"]

        total_pf_a += pts_a
        total_pf_b += pts_b
        margin = abs(pts_a - pts_b)
        margins.append(margin)

        is_playoff = bool(row.get("is_playoff", False)) or bool(row.get("is_championship", False))
        is_champ = bool(row.get("is_championship", False))

        if pts_a > pts_b:
            winner = owner_a
            a_wins += 1
            a_results.append(True)
            if not is_playoff:
                reg_a_wins += 1
            else:
                playoff_a_wins += 1
        elif pts_b > pts_a:
            winner = owner_b
            a_losses += 1
            a_results.append(False)
            if not is_playoff:
                reg_a_losses += 1
            else:
                playoff_a_losses += 1
        else:
            winner = "Tie"
            ties += 1
            a_results.append(True)
            if not is_playoff:
                reg_ties += 1

        m = {
            "season": int(row["season"]),
            "week": int(row["week"]) if pd.notna(row.get("week")) else None,
            "pts_a": round(pts_a, 2),
            "pts_b": round(pts_b, 2),
            "winner": winner,
            "margin": round(margin, 2),
            "is_playoff": is_playoff,
            "is_championship": is_champ,
            "league_id": row.get("league_id", ""),
        }
        meetings.append(m)
        if is_champ:
            champ_meetings.append(m)

    b_results = [not r for r in a_results]

    return {
        "owner_a": owner_a,
        "owner_b": owner_b,
        "all_time_record": (a_wins, a_losses, ties),
        "reg_season_record": (reg_a_wins, reg_a_losses, reg_ties),
        "playoff_record": (playoff_a_wins, playoff_a_losses, 0),
        "championship_matchups": champ_meetings,
        "total_pf_a": round(total_pf_a, 2),
        "total_pf_b": round(total_pf_b, 2),
        "avg_margin": round(sum(margins) / len(margins), 2) if margins else 0.0,
        "largest_win_a": round(max((m["margin"] for m in meetings if m["winner"] == owner_a), default=0.0), 2),
        "largest_win_b": round(max((m["margin"] for m in meetings if m["winner"] == owner_b), default=0.0), 2),
        "closest_game": round(min(margins), 2) if margins else 0.0,
        "win_streak_a": _streak(a_results, True),
        "win_streak_b": _streak(b_results, True),
        "most_consecutive_wins_a": _max_streak(a_results, True),
        "most_consecutive_wins_b": _max_streak(b_results, True),
        "total_meetings": len(meetings),
        "meetings": meetings,
    }


def all_rivalries(matchups_df: pd.DataFrame, league_id: str | None = None) -> pd.DataFrame:
    """One row per unique manager pair with rivalry summary stats.

    Args:
        matchups_df: Full matchups DataFrame.
        league_id: Optional league filter.

    Returns:
        DataFrame with rivalry stats per pair, sorted by rivalry_intensity desc.
    """
    df = _filter_league(matchups_df, league_id)
    df = df.dropna(subset=["points_a", "points_b", "team_a_owner", "team_b_owner"])

    seen: set[tuple[str, str]] = set()
    rows = []

    for _, row in df.iterrows():
        a, b = str(row["team_a_owner"]), str(row["team_b_owner"])
        key = (min(a, b), max(a, b))
        if key not in seen:
            seen.add(key)

    for key in seen:
        owner_a, owner_b = key
        stats = rivalry_stats(df, owner_a, owner_b)
        if stats["total_meetings"] == 0:
            continue
        a_wins, b_wins, ties = stats["all_time_record"]
        total = stats["total_meetings"]
        balance = 1 - abs(a_wins - b_wins) / total if total > 0 else 0
        intensity = round(total * balance, 2)
        rows.append({
            "owner_a": owner_a,
            "owner_b": owner_b,
            "total_games": total,
            "a_wins": a_wins,
            "b_wins": b_wins,
            "ties": ties,
            "avg_margin": stats["avg_margin"],
            "closest_game": stats["closest_game"],
            "biggest_blowout": max(stats["largest_win_a"], stats["largest_win_b"]),
            "rivalry_intensity": intensity,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("rivalry_intensity", ascending=False).reset_index(drop=True)


def rivalry_timeline(
    matchups_df: pd.DataFrame,
    owner_a: str,
    owner_b: str,
) -> pd.DataFrame:
    """All matchup history between two managers sorted chronologically.

    Args:
        matchups_df: Full matchups DataFrame.
        owner_a: First manager name.
        owner_b: Second manager name.

    Returns:
        DataFrame of meetings sorted by season, week.
    """
    stats = rivalry_stats(matchups_df, owner_a, owner_b)
    if not stats["meetings"]:
        return pd.DataFrame()
    df = pd.DataFrame(stats["meetings"])
    df["signed_margin"] = df.apply(
        lambda r: r["margin"] if r["winner"] == owner_a else -r["margin"], axis=1
    )
    return df.sort_values(["season", "week"]).reset_index(drop=True)
