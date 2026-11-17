"""Comprehensive record book: scoring, win/loss, matchup, and draft records."""

from __future__ import annotations

import pandas as pd


def all_records(
    matchups_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_df: pd.DataFrame | None = None,
    league_id: str | None = None,
) -> dict[str, list[dict]]:
    """Return all record categories with top-N leaderboards.

    Args:
        matchups_df: Full matchups table with league_id column.
        rosters_df: Full rosters table with league_id column.
        draft_df: Optional draft_picks table.
        league_id: Filter to one league if provided.

    Returns:
        Dict mapping category name → list of record dicts with keys:
        record, holder, value, context, rank.
    """
    if league_id:
        matchups_df = matchups_df[matchups_df["league_id"] == league_id].copy()
        rosters_df = rosters_df[rosters_df["league_id"] == league_id].copy()
        if draft_df is not None:
            draft_df = draft_df[draft_df["league_id"] == league_id].copy()

    out: dict[str, list[dict]] = {}
    out["Scoring Records"] = _scoring_records(matchups_df)
    out["Win/Loss Records"] = _win_loss_records(matchups_df)
    out["Matchup Records"] = _matchup_records(matchups_df)
    out["Consistency Records"] = _consistency_records(matchups_df)
    out["Season Records"] = _season_records(matchups_df)
    if draft_df is not None and not draft_df.empty:
        out["Draft Records"] = _draft_records(draft_df, matchups_df)
    if not rosters_df.empty:
        out["Lineup Records"] = _lineup_records(rosters_df)
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _top(df: pd.DataFrame, col: str, n: int = 5, ascending: bool = False) -> pd.DataFrame:
    return df.nlargest(n, col) if not ascending else df.nsmallest(n, col)


def _all_scores(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Stack team_a and team_b scores into one frame."""
    a = matchups_df[["season", "week", "team_a_owner", "points_a", "winner_team_id", "team_a_id", "is_playoff", "is_consolation", "is_championship"]].copy()
    a.columns = ["season", "week", "owner", "pts", "winner_id", "team_id", "is_playoff", "is_consolation", "is_championship"]
    b = matchups_df[["season", "week", "team_b_owner", "points_b", "winner_team_id", "team_b_id", "is_playoff", "is_consolation", "is_championship"]].copy()
    b.columns = ["season", "week", "owner", "pts", "winner_id", "team_id", "is_playoff", "is_consolation", "is_championship"]
    combined = pd.concat([a, b], ignore_index=True).dropna(subset=["pts"])
    combined["won"] = combined["team_id"] == combined["winner_id"]
    return combined


def _reg_scores(scores: pd.DataFrame) -> pd.DataFrame:
    return scores[~scores["is_playoff"] & ~scores["is_consolation"] & ~scores["is_championship"]]


def _context(season, week=None, extra: str = "") -> str:
    parts = [str(int(season))]
    if week is not None and pd.notna(week):
        parts.append(f"Wk {int(week)}")
    if extra:
        parts.append(extra)
    return " · ".join(parts)


def _build_records(rows: list[tuple]) -> list[dict]:
    """Build record list from (record_name, holder, value, context) tuples."""
    out = []
    for rank, (record, holder, value, ctx) in enumerate(rows, 1):
        out.append({"rank": rank, "record": record, "holder": holder, "value": value, "context": ctx})
    return out


def _scoring_records(matchups_df: pd.DataFrame) -> list[dict]:
    scores = _all_scores(matchups_df)
    reg = _reg_scores(scores)
    rows = []

    # Highest single-game score (all games)
    top5 = scores.nlargest(5, "pts")
    for _, r in top5.iterrows():
        rows.append(("Highest single-game score", r["owner"], round(r["pts"], 2), _context(r["season"], r["week"])))

    # Highest regular season score
    if not reg.empty:
        t = reg.nlargest(5, "pts")
        for _, r in t.iterrows():
            rows.append(("Highest reg-season score", r["owner"], round(r["pts"], 2), _context(r["season"], r["week"])))

    # Lowest score in a win (reg season)
    if not reg.empty:
        wins = reg[reg["won"]]
        if not wins.empty:
            t = wins.nsmallest(5, "pts")
            for _, r in t.iterrows():
                rows.append(("Lowest score in a win", r["owner"], round(r["pts"], 2), _context(r["season"], r["week"])))

    # Highest score in a loss (reg season)
    if not reg.empty:
        losses = reg[~reg["won"]]
        if not losses.empty:
            t = losses.nlargest(5, "pts")
            for _, r in t.iterrows():
                rows.append(("Highest score in a loss", r["owner"], round(r["pts"], 2), _context(r["season"], r["week"])))

    # Championship game highest score
    champ_scores = scores[scores["is_championship"]]
    if not champ_scores.empty:
        t = champ_scores.nlargest(5, "pts")
        for _, r in t.iterrows():
            rows.append(("Highest championship score", r["owner"], round(r["pts"], 2), _context(r["season"])))

    # Career highest average score (min 20 games)
    career_avg = scores.groupby("owner")["pts"].agg(["mean", "count"]).reset_index()
    career_avg = career_avg[career_avg["count"] >= 20]
    if not career_avg.empty:
        t = career_avg.nlargest(5, "mean")
        for _, r in t.iterrows():
            rows.append(("Best career avg score (≥20 games)", r["owner"], round(r["mean"], 2), f"{int(r['count'])} games"))

    # Highest single-season avg (min 10 games)
    ssn_avg = scores.groupby(["owner", "season"])["pts"].agg(["mean", "count"]).reset_index()
    ssn_avg = ssn_avg[ssn_avg["count"] >= 10]
    if not ssn_avg.empty:
        t = ssn_avg.nlargest(5, "mean")
        for _, r in t.iterrows():
            rows.append(("Best single-season avg score", r["owner"], round(r["mean"], 2), str(int(r["season"]))))

    # Lowest single-season avg (min 10 games, reg season)
    reg_ssn_avg = reg.groupby(["owner", "season"])["pts"].agg(["mean", "count"]).reset_index()
    reg_ssn_avg = reg_ssn_avg[reg_ssn_avg["count"] >= 10]
    if not reg_ssn_avg.empty:
        t = reg_ssn_avg.nsmallest(5, "mean")
        for _, r in t.iterrows():
            rows.append(("Worst single-season avg score", r["owner"], round(r["mean"], 2), str(int(r["season"]))))

    # Most consistent scorer (lowest CV, reg season, min 20 games)
    cv_data = reg.groupby("owner")["pts"].agg(["mean", "std", "count"]).reset_index()
    cv_data = cv_data[cv_data["count"] >= 20]
    if not cv_data.empty:
        cv_data["cv"] = cv_data["std"] / cv_data["mean"].replace(0, pd.NA)
        t = cv_data.nsmallest(5, "cv")
        for _, r in t.iterrows():
            rows.append(("Most consistent scorer", r["owner"], round(float(r["cv"]), 4), f"CV={r['cv']:.4f}"))

    return _build_records(rows)


def _win_loss_records(matchups_df: pd.DataFrame) -> list[dict]:
    reg = matchups_df[~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]].copy()
    rows = []

    # Career reg-season wins
    wins_a = reg[reg["winner_team_id"] == reg["team_a_id"]].groupby("team_a_owner").size().rename("wins")
    wins_b = reg[reg["winner_team_id"] == reg["team_b_id"]].groupby("team_b_owner").size().rename("wins")
    total_wins = pd.concat([wins_a, wins_b]).groupby(level=0).sum().reset_index()
    total_wins.columns = ["owner", "wins"]
    for _, r in total_wins.nlargest(5, "wins").iterrows():
        rows.append(("Most career reg-season wins", r["owner"], int(r["wins"]), "career"))

    # Career reg-season losses
    losses_a = reg[reg["winner_team_id"] != reg["team_a_id"]].groupby("team_a_owner").size().rename("losses")
    losses_b = reg[reg["winner_team_id"] != reg["team_b_id"]].groupby("team_b_owner").size().rename("losses")
    total_losses = pd.concat([losses_a, losses_b]).groupby(level=0).sum().reset_index()
    total_losses.columns = ["owner", "losses"]
    for _, r in total_losses.nlargest(5, "losses").iterrows():
        rows.append(("Most career reg-season losses", r["owner"], int(r["losses"]), "career"))

    # Best single-season win% (min 10 games)
    scores = _all_scores(matchups_df)
    reg_scores = _reg_scores(scores)
    ssn = reg_scores.groupby(["owner", "season"]).agg(
        games=("pts", "count"), wins=("won", "sum")
    ).reset_index()
    ssn = ssn[ssn["games"] >= 10]
    ssn["win_pct"] = ssn["wins"] / ssn["games"]
    if not ssn.empty:
        for _, r in ssn.nlargest(5, "win_pct").iterrows():
            rows.append(("Best single-season win%", r["owner"], f"{r['win_pct']:.3f}", f"{int(r['season'])} ({int(r['wins'])}-{int(r['games']-r['wins'])})"))
        for _, r in ssn.nsmallest(5, "win_pct").iterrows():
            rows.append(("Worst single-season win%", r["owner"], f"{r['win_pct']:.3f}", f"{int(r['season'])} ({int(r['wins'])}-{int(r['games']-r['wins'])})"))

    # Longest win streak
    streaks = _streak_records(matchups_df)
    for r in sorted(streaks, key=lambda x: -x["max_win_streak"])[:5]:
        rows.append(("Longest win streak", r["owner"], r["max_win_streak"], "regular season"))

    # Longest loss streak
    for r in sorted(streaks, key=lambda x: -x["max_loss_streak"])[:5]:
        rows.append(("Longest loss streak", r["owner"], r["max_loss_streak"], "regular season"))

    # Championships
    champ_counts = matchups_df[matchups_df["is_championship"]].copy()
    if not champ_counts.empty:
        champ_counts["champion"] = champ_counts.apply(
            lambda r: r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"], axis=1
        )
        champ_tally = champ_counts.groupby("champion").size().reset_index(name="count")
        for _, r in champ_tally.nlargest(5, "count").iterrows():
            rows.append(("Most championships", r["champion"], int(r["count"]), "all-time"))

    return _build_records(rows)


def _matchup_records(matchups_df: pd.DataFrame) -> list[dict]:
    rows = []
    df = matchups_df.dropna(subset=["points_a", "points_b"]).copy()
    df["margin"] = (df["points_a"] - df["points_b"]).abs()
    df["total"] = df["points_a"] + df["points_b"]
    df["winner_pts"] = df.apply(lambda r: r["points_a"] if r["winner_team_id"] == r["team_a_id"] else r["points_b"], axis=1)
    df["loser_pts"] = df.apply(lambda r: r["points_b"] if r["winner_team_id"] == r["team_a_id"] else r["points_a"], axis=1)

    # Largest margin of victory
    for _, r in df.nlargest(5, "margin").iterrows():
        winner = r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"]
        rows.append(("Largest margin of victory", winner, round(r["margin"], 2), _context(r["season"], r["week"])))

    # Smallest margin of victory (closest game)
    for _, r in df.nsmallest(5, "margin").iterrows():
        winner = r["team_a_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_b_owner"]
        rows.append(("Closest game (smallest margin)", winner, round(r["margin"], 2), _context(r["season"], r["week"])))

    # Highest combined score
    for _, r in df.nlargest(5, "total").iterrows():
        ctx = f"{r['team_a_owner']} vs {r['team_b_owner']}"
        rows.append(("Highest combined score", ctx, round(r["total"], 2), _context(r["season"], r["week"])))

    # Lowest combined score
    reg = df[~df["is_playoff"] & ~df["is_consolation"] & ~df["is_championship"]]
    if not reg.empty:
        for _, r in reg.nsmallest(5, "total").iterrows():
            ctx = f"{r['team_a_owner']} vs {r['team_b_owner']}"
            rows.append(("Lowest combined score", ctx, round(r["total"], 2), _context(r["season"], r["week"])))

    # Highest losing score (moral victory)
    for _, r in df.nlargest(5, "loser_pts").iterrows():
        loser = r["team_b_owner"] if r["winner_team_id"] == r["team_a_id"] else r["team_a_owner"]
        rows.append(("Highest score in a loss", loser, round(r["loser_pts"], 2), _context(r["season"], r["week"])))

    # Upset index: lowest-scoring win vs highest opponent
    # (covered in scoring records; skip duplicate)

    return _build_records(rows)


def _consistency_records(matchups_df: pd.DataFrame) -> list[dict]:
    scores = _all_scores(matchups_df)
    reg = _reg_scores(scores)
    rows = []

    if reg.empty:
        return []

    # Most 150+ point games
    high_games = reg[reg["pts"] >= 150].groupby("owner").size().reset_index(name="count")
    for _, r in high_games.nlargest(5, "count").iterrows():
        rows.append(("Most 150+ point games", r["owner"], int(r["count"]), "regular season"))

    # Most sub-100 point games
    low_games = reg[reg["pts"] < 100].groupby("owner").size().reset_index(name="count")
    for _, r in low_games.nlargest(5, "count").iterrows():
        rows.append(("Most sub-100 point games", r["owner"], int(r["count"]), "regular season"))

    # Highest single-week score (all seasons)
    week_max = reg.groupby(["owner", "season"])["pts"].max().reset_index(name="week_max")
    season_high = week_max.groupby("owner")["week_max"].max().reset_index()
    for _, r in season_high.nlargest(5, "week_max").iterrows():
        rows.append(("Personal best single-game score", r["owner"], round(r["week_max"], 2), "regular season"))

    # 100+ point streak (longest)
    streak_100 = _consecutive_streak(reg, "pts", 100.0, above=True)
    for r in sorted(streak_100, key=lambda x: -x["streak"])[:5]:
        rows.append(("Longest 100+ point streak", r["owner"], r["streak"], "regular season weeks"))

    return _build_records(rows)


def _season_records(matchups_df: pd.DataFrame) -> list[dict]:
    scores = _all_scores(matchups_df)
    reg = _reg_scores(scores)
    rows = []

    if reg.empty:
        return []

    # Most points in a single season
    ssn_pf = reg.groupby(["owner", "season"])["pts"].sum().reset_index(name="total_pts")
    for _, r in ssn_pf.nlargest(5, "total_pts").iterrows():
        rows.append(("Most points in a season", r["owner"], round(r["total_pts"], 2), str(int(r["season"]))))

    # Fewest points in a season (min 10 games)
    ssn_pf_cnt = reg.groupby(["owner", "season"]).agg(total_pts=("pts", "sum"), games=("pts", "count")).reset_index()
    ssn_pf_cnt = ssn_pf_cnt[ssn_pf_cnt["games"] >= 10]
    if not ssn_pf_cnt.empty:
        for _, r in ssn_pf_cnt.nsmallest(5, "total_pts").iterrows():
            rows.append(("Fewest points in a season", r["owner"], round(r["total_pts"], 2), str(int(r["season"]))))

    # Most seasons played
    seasons_played = reg.groupby("owner")["season"].nunique().reset_index(name="seasons")
    for _, r in seasons_played.nlargest(5, "seasons").iterrows():
        rows.append(("Most seasons played", r["owner"], int(r["seasons"]), "all-time"))

    # Perfect regular season (most wins in one season)
    ssn_wins = reg.groupby(["owner", "season"]).agg(wins=("won", "sum"), games=("pts", "count")).reset_index()
    ssn_wins["win_pct"] = ssn_wins["wins"] / ssn_wins["games"]
    perfect = ssn_wins[ssn_wins["win_pct"] == 1.0]
    if not perfect.empty:
        for _, r in perfect.sort_values("wins", ascending=False).head(5).iterrows():
            rows.append(("Perfect regular season", r["owner"], int(r["wins"]), f"{int(r['season'])} ({int(r['wins'])}-0)"))

    # Worst record in a season (most losses)
    ssn_losses = ssn_wins.copy()
    ssn_losses["losses"] = ssn_losses["games"] - ssn_losses["wins"]
    for _, r in ssn_losses.nlargest(5, "losses").iterrows():
        rows.append(("Most losses in a season", r["owner"], int(r["losses"]), f"{int(r['season'])} ({int(r['wins'])}-{int(r['losses'])})"))

    return _build_records(rows)


def _draft_records(draft_df: pd.DataFrame, matchups_df: pd.DataFrame) -> list[dict]:
    rows = []
    scores = _all_scores(matchups_df)

    # Most keepers ever
    if "keeper" in draft_df.columns:
        keepers = draft_df[draft_df["keeper"] == True]
        if not keepers.empty:
            keeper_counts = keepers.groupby("owner_name").size().reset_index(name="count")
            for _, r in keeper_counts.nlargest(5, "count").iterrows():
                rows.append(("Most keepers drafted", r["owner_name"], int(r["count"]), "all-time"))

    # Most 1st-round picks (round 1)
    if "round" in draft_df.columns:
        r1 = draft_df[draft_df["round"] == 1].groupby("owner_name").size().reset_index(name="count")
        for _, r in r1.nlargest(5, "count").iterrows():
            rows.append(("Most 1st-round picks (all seasons)", r["owner"], int(r["count"]), "all-time"))

    # Most QBs drafted
    if "position" in draft_df.columns:
        pos_counts = draft_df.groupby(["owner_name", "position"]).size().unstack(fill_value=0).reset_index()
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            if pos in pos_counts.columns:
                for _, r in pos_counts.nlargest(5, pos).iterrows():
                    rows.append((f"Most {pos}s drafted", r["owner_name"], int(r[pos]), "all-time"))

    return _build_records(rows)


def _lineup_records(rosters_df: pd.DataFrame) -> list[dict]:
    rows = []
    starters = rosters_df[rosters_df["starter"] == True].dropna(subset=["points"])

    if starters.empty:
        return []

    # Highest single-player game by a starter
    top_perf = starters.nlargest(5, "points")
    for _, r in top_perf.iterrows():
        ctx = f"{r['player']} ({r.get('position','?')}) · Wk {r.get('week','?')}"
        rows.append(("Best single-player starter performance", r["owner_name"], round(r["points"], 2), f"{int(r['season'])} {ctx}"))

    # Highest single-week starter total
    week_total = starters.groupby(["owner_name", "season", "week"])["points"].sum().reset_index(name="total")
    for _, r in week_total.nlargest(5, "total").iterrows():
        rows.append(("Highest starter total in one week", r["owner_name"], round(r["total"], 2), _context(r["season"], r["week"])))

    # Most points left on bench (missed points = bench total when bench > starting lineup)
    if "starter" in rosters_df.columns:
        bench = rosters_df[rosters_df["starter"] == False].dropna(subset=["points"])
        bench_wk = bench.groupby(["owner_name", "season", "week"])["points"].sum().reset_index(name="bench_pts")
        for _, r in bench_wk.nlargest(5, "bench_pts").iterrows():
            rows.append(("Most points left on bench (single week)", r["owner_name"], round(r["bench_pts"], 2), _context(r["season"], r["week"])))

    return _build_records(rows)


def _streak_records(matchups_df: pd.DataFrame) -> list[dict]:
    reg = matchups_df[
        ~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]
    ].copy().dropna(subset=["week"]).sort_values(["season", "week"])

    owner_results: dict[str, list[bool]] = {}
    for _, row in reg.iterrows():
        for owner, team_id in [
            (row["team_a_owner"], row["team_a_id"]),
            (row["team_b_owner"], row["team_b_id"]),
        ]:
            if not owner:
                continue
            if owner not in owner_results:
                owner_results[owner] = []
            owner_results[owner].append(team_id == row["winner_team_id"])

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


def _consecutive_streak(
    scores: pd.DataFrame,
    col: str,
    threshold: float,
    above: bool = True,
) -> list[dict]:
    """Compute longest streak of games above/below threshold per owner."""
    out = []
    for owner, grp in scores.groupby("owner"):
        grp = grp.sort_values(["season", "week"])
        max_streak = cur = 0
        for pts in grp[col]:
            cond = pts >= threshold if above else pts < threshold
            if cond:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        if max_streak > 0:
            out.append({"owner": owner, "streak": max_streak})
    return out
