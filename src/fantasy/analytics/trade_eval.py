"""Trade evaluation: per-trade grades, drop regret, and manager trade leaderboard."""

from __future__ import annotations

import json

import pandas as pd

_EMPTY_EVAL_COLS = [
    "season", "week", "league_id", "trade_id", "owner",
    "players_acquired", "players_surrendered",
    "acq_total_points", "sur_total_points",
    "acq_started_points", "sur_started_points",
    "acq_starter_weeks", "sur_starter_weeks",
    "net_started_points", "verdict",
]

_EMPTY_REGRET_COLS = [
    "season", "week", "league_id", "owner_drop", "dropped_player",
    "weeks_remaining", "future_total_points", "future_started_points",
    "future_started_weeks", "regret_score", "verdict",
]

_REGULAR_SEASON_WEEKS = 14


def _parse_trade_parties(parties_raw) -> list[str]:
    try:
        parties = json.loads(parties_raw) if isinstance(parties_raw, str) else (parties_raw or [])
        return [
            str(p.get("team") or p.get("teamName") or "")
            for p in parties
            if isinstance(p, dict)
        ]
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_trade_players(players_raw) -> list[dict]:
    try:
        players = json.loads(players_raw) if isinstance(players_raw, str) else (players_raw or [])
        return [p for p in players if isinstance(p, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def _player_points(rosters_df: pd.DataFrame, player: str, season: int, min_week: int) -> dict:
    mask = (
        (rosters_df["player"] == player)
        & (rosters_df["season"] == season)
        & (rosters_df["week"] >= min_week)
    )
    rows = rosters_df[mask]
    starters = rows[rows["starter"] == True]
    return {
        "total": float(rows["points"].fillna(0).sum()),
        "started": float(starters["points"].fillna(0).sum()),
        "starter_weeks": int(starters.shape[0]),
    }


def evaluate_all_trades(
    transactions_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
) -> pd.DataFrame:
    empty = pd.DataFrame(columns=_EMPTY_EVAL_COLS)
    if transactions_df.empty or rosters_df.empty:
        return empty

    trades = transactions_df[transactions_df["type"] == "trade"].copy()
    if trades.empty:
        return empty

    rows: list[dict] = []
    trade_id = 0

    for _, t in trades.iterrows():
        season = int(t.get("season", 0)) if t.get("season") is not None else 0
        week = int(t.get("week", 1)) if t.get("week") is not None else 1
        league_id = t.get("league_id", "")

        teams = _parse_trade_parties(t.get("parties"))
        if len(teams) < 2:
            continue
        team_a, team_b = teams[0], teams[1]

        players = _parse_trade_players(t.get("players"))
        gave_a: list[str] = []
        gave_b: list[str] = []
        for p in players:
            pname = p.get("player") or p.get("name") or ""
            if not pname:
                continue
            from_team = (p.get("from") or {}).get("team", "")
            if from_team == team_a:
                gave_a.append(pname)
            elif from_team == team_b:
                gave_b.append(pname)

        if not gave_a and not gave_b:
            continue

        def side_stats(acquired: list[str], surrendered: list[str]) -> dict:
            at = asts = aw = st = ssts = sw = 0.0
            aw_int = sw_int = 0
            for p in acquired:
                r = _player_points(rosters_df, p, season, week)
                at += r["total"]
                asts += r["started"]
                aw_int += r["starter_weeks"]
            for p in surrendered:
                r = _player_points(rosters_df, p, season, week)
                st += r["total"]
                ssts += r["started"]
                sw_int += r["starter_weeks"]
            net = asts - ssts
            if net > 5:
                verdict = "Won"
            elif net < -5:
                verdict = "Lost"
            else:
                verdict = "Even"
            return {
                "acq_total_points": round(at, 2),
                "sur_total_points": round(st, 2),
                "acq_started_points": round(asts, 2),
                "sur_started_points": round(ssts, 2),
                "acq_starter_weeks": aw_int,
                "sur_starter_weeks": sw_int,
                "net_started_points": round(net, 2),
                "verdict": verdict,
            }

        s_a = side_stats(gave_b, gave_a)
        s_b = side_stats(gave_a, gave_b)

        for owner, acquired, surrendered, stats in [
            (team_a, gave_b, gave_a, s_a),
            (team_b, gave_a, gave_b, s_b),
        ]:
            rows.append({
                "season": season,
                "week": week,
                "league_id": league_id,
                "trade_id": trade_id,
                "owner": owner,
                "players_acquired": ", ".join(acquired) or "—",
                "players_surrendered": ", ".join(surrendered) or "—",
                **stats,
            })

        trade_id += 1

    return pd.DataFrame(rows, columns=_EMPTY_EVAL_COLS) if rows else empty


def player_drop_regret(
    transactions_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
) -> pd.DataFrame:
    empty = pd.DataFrame(columns=_EMPTY_REGRET_COLS)
    if transactions_df.empty or rosters_df.empty:
        return empty

    drops = transactions_df[transactions_df["type"].isin(("drop", "add/drop"))].copy()
    if drops.empty:
        return empty

    rows: list[dict] = []

    for _, t in drops.iterrows():
        season = int(t.get("season", 0)) if t.get("season") is not None else 0
        week = int(t.get("week", 1)) if t.get("week") is not None else 1
        league_id = t.get("league_id", "")

        try:
            parties_raw = t.get("parties")
            parties = json.loads(parties_raw) if isinstance(parties_raw, str) else (parties_raw or [])
        except (json.JSONDecodeError, TypeError):
            parties = []

        drop_owner = ""
        for p in parties:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "drop":
                drop_owner = str(p.get("owner") or p.get("name") or p.get("teamName") or "")
                break

        try:
            players_raw = t.get("players")
            players = json.loads(players_raw) if isinstance(players_raw, str) else (players_raw or [])
        except (json.JSONDecodeError, TypeError):
            players = []

        for p in players:
            if not isinstance(p, dict):
                continue
            if p.get("type") != "drop" and p.get("action") != "drop":
                continue
            pname = p.get("player") or p.get("name") or ""
            if not pname:
                continue

            future_week = week + 1
            if future_week > _REGULAR_SEASON_WEEKS:
                continue

            r = _player_points(rosters_df, pname, season, future_week)
            weeks_remaining = max(0, _REGULAR_SEASON_WEEKS - week)
            regret = r["started"]

            if regret > 30:
                verdict = "High Regret"
            elif regret > 15:
                verdict = "Medium Regret"
            else:
                verdict = "Low Regret"

            rows.append({
                "season": season,
                "week": week,
                "league_id": league_id,
                "owner_drop": drop_owner,
                "dropped_player": pname,
                "weeks_remaining": weeks_remaining,
                "future_total_points": round(r["total"], 2),
                "future_started_points": round(r["started"], 2),
                "future_started_weeks": r["starter_weeks"],
                "regret_score": round(regret, 2),
                "verdict": verdict,
            })

    return pd.DataFrame(rows, columns=_EMPTY_REGRET_COLS) if rows else empty


def trade_leaderboard(trade_eval_df: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=[
        "owner", "total_trades", "trades_won", "trades_lost", "trades_even",
        "total_net_started_points", "avg_net_per_trade",
    ])
    if trade_eval_df.empty or "owner" not in trade_eval_df.columns:
        return empty

    rows: list[dict] = []
    for owner, grp in trade_eval_df.groupby("owner"):
        won = int((grp["verdict"] == "Won").sum())
        lost = int((grp["verdict"] == "Lost").sum())
        even = int((grp["verdict"] == "Even").sum())
        total = len(grp)
        net = float(grp["net_started_points"].sum())
        rows.append({
            "owner": owner,
            "total_trades": total,
            "trades_won": won,
            "trades_lost": lost,
            "trades_even": even,
            "total_net_started_points": round(net, 2),
            "avg_net_per_trade": round(net / total, 2) if total else 0.0,
        })

    return pd.DataFrame(rows).sort_values("total_net_started_points", ascending=False).reset_index(drop=True)
