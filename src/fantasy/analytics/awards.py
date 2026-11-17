"""Automated fantasy league awards computed from historical data."""

from __future__ import annotations

import pandas as pd


def _filter_league(df: pd.DataFrame, league_id: str | None) -> pd.DataFrame:
    if league_id and "league_id" in df.columns:
        return df[df["league_id"] == league_id].copy()
    return df


def _regular_season(matchups_df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = matchups_df[matchups_df["season"] == season]
    return df[~df["is_playoff"] & ~df["is_consolation"] & ~df["is_championship"]].copy()


def _safe_first(df: pd.DataFrame, col: str, ascending: bool = False) -> tuple[str, float] | tuple[None, None]:
    if df.empty:
        return None, None
    df = df.sort_values(col, ascending=ascending).reset_index(drop=True)
    return df.iloc[0]["owner"], df.iloc[0][col]


def season_awards(
    matchups_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_picks_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> dict[str, dict]:
    """Compute season awards for a given year.

    Args:
        matchups_df: Full matchups DataFrame.
        rosters_df: Full rosters DataFrame.
        draft_picks_df: Full draft picks DataFrame.
        season: Season year (e.g. 2023).
        league_id: League filter, or None for all.

    Returns:
        Dict mapping award name to {winner, value, description, runner_up}.
    """
    matchups_df = _filter_league(matchups_df, league_id)
    rosters_df = _filter_league(rosters_df, league_id)
    draft_picks_df = _filter_league(draft_picks_df, league_id)

    awards: dict[str, dict] = {}

    # --- standings-based awards ---
    try:
        from fantasy.analytics.standings import season_standings

        st = season_standings(matchups_df, season, league_id)
        if not st.empty:
            st_sorted = st.sort_values(["total_wins", "points_for"], ascending=False).reset_index(drop=True)
            awards["Manager of the Year"] = {
                "winner": st_sorted.iloc[0]["owner"],
                "value": f"{int(st_sorted.iloc[0]['total_wins'])}W",
                "description": "Best overall record (regular season)",
                "runner_up": st_sorted.iloc[1]["owner"] if len(st_sorted) > 1 else None,
            }
            awards["Regular Season Champion"] = awards["Manager of the Year"]
            awards["Highest Scorer"] = {
                "winner": st.loc[st["points_for"].idxmax(), "owner"],
                "value": f"{st['points_for'].max():.1f} pts",
                "description": "Most total regular-season points",
                "runner_up": None,
            }
            awards["Last Place"] = {
                "winner": st_sorted.iloc[-1]["owner"],
                "value": f"{int(st_sorted.iloc[-1]['total_wins'])}W",
                "description": "Fewest wins (regular season)",
                "runner_up": None,
            }
            if "points_against" in st.columns:
                awards["Most Points Against"] = {
                    "winner": st.loc[st["points_against"].idxmax(), "owner"],
                    "value": f"{st['points_against'].max():.1f} pts",
                    "description": "Faced the most total points — toughest schedule",
                    "runner_up": None,
                }
    except Exception:
        pass

    # --- champion ---
    try:
        champ_m = matchups_df[(matchups_df["season"] == season) & matchups_df["is_championship"]]
        if not champ_m.empty:
            row = champ_m.iloc[0]
            if row["winner_team_id"] == row["team_a_id"]:
                champ, runner = row["team_a_owner"], row["team_b_owner"]
                score = f"{row['points_a']:.2f}–{row['points_b']:.2f}"
            else:
                champ, runner = row["team_b_owner"], row["team_a_owner"]
                score = f"{row['points_b']:.2f}–{row['points_a']:.2f}"
            awards["Champion"] = {
                "winner": champ,
                "value": score,
                "description": "Championship winner",
                "runner_up": runner,
            }
    except Exception:
        pass

    # --- highest single-week score ---
    try:
        reg = _regular_season(matchups_df, season)
        if not reg.empty:
            scores = pd.concat([
                reg[["team_a_owner", "week", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
                reg[["team_b_owner", "week", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
            ]).dropna()
            if not scores.empty:
                top = scores.loc[scores["pts"].idxmax()]
                awards["Scoring Machine"] = {
                    "winner": top["owner"],
                    "value": f"{top['pts']:.2f} pts (Wk {int(top['week'])})",
                    "description": "Highest single-week score",
                    "runner_up": None,
                }
    except Exception:
        pass

    # --- luck awards ---
    try:
        from fantasy.analytics.luck import luck_metrics

        luck = luck_metrics(matchups_df, season, league_id)
        if not luck.empty:
            luck_s = luck.sort_values("luck_delta", ascending=False).reset_index(drop=True)
            awards["Luckiest Manager"] = {
                "winner": luck_s.iloc[0]["owner"],
                "value": f"+{luck_s.iloc[0]['luck_delta']:.2f} wins",
                "description": "Actual wins far exceeded expected wins",
                "runner_up": luck_s.iloc[1]["owner"] if len(luck_s) > 1 else None,
            }
            awards["Unluckiest Manager"] = {
                "winner": luck_s.iloc[-1]["owner"],
                "value": f"{luck_s.iloc[-1]['luck_delta']:.2f} wins",
                "description": "Deserved far better — schedule was cruel",
                "runner_up": None,
            }
    except Exception:
        pass

    # --- schedule difficulty (avg opponent score) ---
    try:
        reg = _regular_season(matchups_df, season)
        if not reg.empty:
            reg = reg.dropna(subset=["points_a", "points_b"])
            opp_a = reg[["team_a_owner", "points_b"]].rename(columns={"team_a_owner": "owner", "points_b": "opp_pts"})
            opp_b = reg[["team_b_owner", "points_a"]].rename(columns={"team_b_owner": "owner", "points_a": "opp_pts"})
            opp_all = pd.concat([opp_a, opp_b])
            sched = opp_all.groupby("owner")["opp_pts"].mean().reset_index(name="avg_opp_pts")
            if len(sched) >= 2:
                hardest = sched.loc[sched["avg_opp_pts"].idxmax()]
                easiest = sched.loc[sched["avg_opp_pts"].idxmin()]
                awards["Hardest Schedule"] = {
                    "winner": hardest["owner"],
                    "value": f"{hardest['avg_opp_pts']:.1f} avg opp pts/wk",
                    "description": "Faced the toughest opponents on average",
                    "runner_up": None,
                }
                awards["Luckiest Schedule"] = {
                    "winner": easiest["owner"],
                    "value": f"{easiest['avg_opp_pts']:.1f} avg opp pts/wk",
                    "description": "Faced the weakest opponents on average — easiest path",
                    "runner_up": None,
                }
    except Exception:
        pass

    # --- blowout king / glass jaw ---
    try:
        reg = _regular_season(matchups_df, season)
        if not reg.empty:
            reg = reg.dropna(subset=["points_a", "points_b"])
            reg["margin"] = (reg["points_a"] - reg["points_b"]).abs()
            blowout = reg[reg["margin"] > 30]
            if not blowout.empty:
                wins_by = {}
                losses_by = {}
                for _, row in blowout.iterrows():
                    winner_own = row["team_a_owner"] if row["winner_team_id"] == row["team_a_id"] else row["team_b_owner"]
                    loser_own = row["team_b_owner"] if row["winner_team_id"] == row["team_a_id"] else row["team_a_owner"]
                    wins_by[winner_own] = wins_by.get(winner_own, 0) + 1
                    losses_by[loser_own] = losses_by.get(loser_own, 0) + 1
                if wins_by:
                    bk = max(wins_by, key=wins_by.__getitem__)
                    awards["Blowout King"] = {
                        "winner": bk,
                        "value": f"{wins_by[bk]} blowout win(s)",
                        "description": "Most wins by 30+ points",
                        "runner_up": None,
                    }
                if losses_by:
                    gj = max(losses_by, key=losses_by.__getitem__)
                    awards["Glass Jaw"] = {
                        "winner": gj,
                        "value": f"{losses_by[gj]} blowout loss(es)",
                        "description": "Most losses by 30+ points",
                        "runner_up": None,
                    }
    except Exception:
        pass

    # --- lineup efficiency ---
    try:
        from fantasy.analytics.lineups import lineup_efficiency_summary

        s_rosters = rosters_df[rosters_df["season"] == season]
        eff = lineup_efficiency_summary(s_rosters, season, league_id)
        if not eff.empty:
            eff_s = eff.sort_values("avg_efficiency", ascending=False).reset_index(drop=True)
            awards["Lineup Wizard"] = {
                "winner": eff_s.iloc[0]["owner"],
                "value": f"{eff_s.iloc[0]['avg_efficiency'] * 100:.1f}% efficiency",
                "description": "Highest average lineup efficiency (actual / optimal)",
                "runner_up": eff_s.iloc[1]["owner"] if len(eff_s) > 1 else None,
            }
            bench_s = eff.sort_values("total_points_left", ascending=False).reset_index(drop=True)
            awards["Bench Disaster"] = {
                "winner": bench_s.iloc[0]["owner"],
                "value": f"{bench_s.iloc[0]['total_points_left']:.1f} pts left",
                "description": "Most total points left on bench all season",
                "runner_up": None,
            }
    except Exception:
        pass

    # --- draft awards ---
    try:
        s_draft = draft_picks_df[draft_picks_df["season"] == season]
        s_rosters = rosters_df[rosters_df["season"] == season]
        if not s_draft.empty and not s_rosters.empty:
            player_pts = s_rosters.groupby("player")["points"].sum().reset_index().rename(columns={"points": "total_points"})
            draft_perf = s_draft.merge(player_pts, on="player", how="left")
            draft_perf["total_points"] = draft_perf["total_points"].fillna(0.0)
            draft_perf["pick_value"] = draft_perf["total_points"] / draft_perf["round"].replace(0, float("nan"))
            mgr_draft = draft_perf.groupby("owner_name")["pick_value"].mean().reset_index()
            mgr_draft = mgr_draft[mgr_draft.index.isin(
                draft_perf.groupby("owner_name").size()[lambda s: s >= 5].index
            ) | (draft_perf.groupby("owner_name").size() >= 5)]
            mgr_draft = draft_perf[draft_perf["owner_name"].map(
                draft_perf.groupby("owner_name").size() >= 5
            )].groupby("owner_name")["pick_value"].mean().reset_index()
            if not mgr_draft.empty:
                best_idx = mgr_draft["pick_value"].idxmax()
                worst_idx = mgr_draft["pick_value"].idxmin()
                awards["Best Drafter"] = {
                    "winner": mgr_draft.loc[best_idx, "owner_name"],
                    "value": f"{mgr_draft.loc[best_idx, 'pick_value']:.1f} pts/round",
                    "description": "Highest average points per draft round",
                    "runner_up": None,
                }
                awards["Worst Drafter"] = {
                    "winner": mgr_draft.loc[worst_idx, "owner_name"],
                    "value": f"{mgr_draft.loc[worst_idx, 'pick_value']:.1f} pts/round",
                    "description": "Lowest average points per draft round",
                    "runner_up": None,
                }
    except Exception:
        pass

    return awards


def all_time_awards(
    matchups_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_picks_df: pd.DataFrame,
    league_id: str | None = None,
) -> dict[str, dict]:
    """Compute career all-time awards across all seasons.

    Args:
        matchups_df: Full matchups DataFrame.
        rosters_df: Full rosters DataFrame.
        draft_picks_df: Full draft picks DataFrame.
        league_id: League filter, or None for all.

    Returns:
        Dict mapping award name to {winner, value, description, runner_up}.
    """
    matchups_df = _filter_league(matchups_df, league_id)
    rosters_df = _filter_league(rosters_df, league_id)
    draft_picks_df = _filter_league(draft_picks_df, league_id)

    awards: dict[str, dict] = {}

    # --- career standings ---
    try:
        from fantasy.analytics.standings import career_standings

        career = career_standings(matchups_df, league_id)
        if not career.empty:
            awards["Most Career Wins"] = {
                "winner": career.iloc[0]["owner"] if career["h2h_wins"].iloc[0] >= career["h2h_wins"].max() else career.loc[career["h2h_wins"].idxmax(), "owner"],
                "value": f"{int(career['h2h_wins'].max())} wins",
                "description": "Most career H2H wins",
                "runner_up": None,
            }
            career_w = career.loc[career["h2h_wins"].idxmax()]
            awards["Most Career Wins"] = {
                "winner": career_w["owner"],
                "value": f"{int(career_w['h2h_wins'])} wins",
                "description": "Most career H2H wins",
                "runner_up": None,
            }
            qual = career[career["seasons_played"] >= 2]
            if not qual.empty:
                best_pct = qual.loc[qual["h2h_win_pct"].idxmax()]
                awards["Highest Career Win%"] = {
                    "winner": best_pct["owner"],
                    "value": f"{best_pct['h2h_win_pct']:.3f}",
                    "description": f"Best H2H win% (min 2 seasons, {int(best_pct['seasons_played'])} seasons played)",
                    "runner_up": None,
                }
            most_pts = career.loc[career["points_for"].idxmax()]
            awards["Most Career Points"] = {
                "winner": most_pts["owner"],
                "value": f"{most_pts['points_for']:.1f} pts",
                "description": "Highest total points across all seasons",
                "runner_up": None,
            }
    except Exception:
        pass

    # --- championships ---
    try:
        champ_ms = matchups_df[matchups_df["is_championship"]].copy()
        if not champ_ms.empty:
            champs = []
            for _, row in champ_ms.iterrows():
                if row["winner_team_id"] == row["team_a_id"]:
                    champs.append((row["season"], row["team_a_owner"]))
                else:
                    champs.append((row["season"], row["team_b_owner"]))
            champ_df = pd.DataFrame(champs, columns=["season", "owner"])
            champ_counts = champ_df["owner"].value_counts()
            if not champ_counts.empty:
                awards["Most Championships"] = {
                    "winner": champ_counts.index[0],
                    "value": f"{champ_counts.iloc[0]} title(s)",
                    "description": "Most total championships",
                    "runner_up": champ_counts.index[1] if len(champ_counts) > 1 else None,
                }
            # Consecutive championships
            champ_df = champ_df.sort_values("season")
            best_streak = 0
            best_streak_owner = None
            for owner in champ_df["owner"].unique():
                seasons = sorted(champ_df[champ_df["owner"] == owner]["season"].tolist())
                streak = cur = 1
                for i in range(1, len(seasons)):
                    if seasons[i] == seasons[i - 1] + 1:
                        cur += 1
                        streak = max(streak, cur)
                    else:
                        cur = 1
                if streak > best_streak:
                    best_streak, best_streak_owner = streak, owner
            if best_streak_owner:
                awards["Most Consecutive Championships"] = {
                    "winner": best_streak_owner,
                    "value": f"{best_streak} in a row",
                    "description": "Most consecutive championship wins",
                    "runner_up": None,
                }
            # Longest drought
            all_seasons = sorted(matchups_df["season"].unique())
            if all_seasons:
                current_year = max(all_seasons)
                drought_data = {}
                for owner in matchups_df["team_a_owner"].dropna().unique():
                    owner_champs = champ_df[champ_df["owner"] == owner]["season"].tolist()
                    last_champ = max(owner_champs) if owner_champs else None
                    seasons_played = len(matchups_df[
                        (matchups_df["team_a_owner"] == owner) | (matchups_df["team_b_owner"] == owner)
                    ]["season"].unique())
                    if seasons_played >= 2:
                        drought = current_year - last_champ if last_champ else seasons_played
                        drought_data[owner] = drought
                if drought_data:
                    worst = max(drought_data, key=drought_data.__getitem__)
                    awards["Longest Championship Drought"] = {
                        "winner": worst,
                        "value": f"{drought_data[worst]} season(s)",
                        "description": "Seasons since last championship (or never won)",
                        "runner_up": None,
                    }
    except Exception:
        pass

    # --- luck career ---
    try:
        from fantasy.analytics.luck import luck_metrics

        all_luck = []
        for season in sorted(matchups_df["season"].unique()):
            lk = luck_metrics(matchups_df, int(season), league_id)
            if not lk.empty:
                lk["season"] = season
                all_luck.append(lk)
        if all_luck:
            luck_all = pd.concat(all_luck, ignore_index=True)
            career_luck = luck_all.groupby("owner")["luck_delta"].sum().reset_index()
            luckiest = career_luck.loc[career_luck["luck_delta"].idxmax()]
            unluckiest = career_luck.loc[career_luck["luck_delta"].idxmin()]
            awards["Luckiest Career"] = {
                "winner": luckiest["owner"],
                "value": f"+{luckiest['luck_delta']:.1f} wins",
                "description": "Lifetime luck surplus — benefited most from favorable schedules",
                "runner_up": None,
            }
            awards["Unluckiest Career"] = {
                "winner": unluckiest["owner"],
                "value": f"{unluckiest['luck_delta']:.1f} wins",
                "description": "Lifetime luck deficit — consistently deserved better",
                "runner_up": None,
            }
    except Exception:
        pass

    # --- career schedule difficulty ---
    try:
        reg_all_sched = matchups_df[
            ~matchups_df["is_playoff"].fillna(False) &
            ~matchups_df["is_consolation"].fillna(False) &
            ~matchups_df["is_championship"].fillna(False)
        ].dropna(subset=["points_a", "points_b"])
        if not reg_all_sched.empty:
            opp_a = reg_all_sched[["team_a_owner", "points_b"]].rename(columns={"team_a_owner": "owner", "points_b": "opp_pts"})
            opp_b = reg_all_sched[["team_b_owner", "points_a"]].rename(columns={"team_b_owner": "owner", "points_a": "opp_pts"})
            opp_all = pd.concat([opp_a, opp_b])
            sched = opp_all.groupby("owner")["opp_pts"].mean().reset_index(name="avg_opp_pts")
            if len(sched) >= 2:
                hardest = sched.loc[sched["avg_opp_pts"].idxmax()]
                easiest = sched.loc[sched["avg_opp_pts"].idxmin()]
                awards["Hardest Schedule (Career)"] = {
                    "winner": hardest["owner"],
                    "value": f"{hardest['avg_opp_pts']:.1f} avg opp pts/wk",
                    "description": "Faced the toughest opponents on average across all seasons",
                    "runner_up": None,
                }
                awards["Luckiest Schedule (Career)"] = {
                    "winner": easiest["owner"],
                    "value": f"{easiest['avg_opp_pts']:.1f} avg opp pts/wk",
                    "description": "Faced the weakest opponents on average — easiest career path",
                    "runner_up": None,
                }
    except Exception:
        pass

    # --- best single week ever ---
    try:
        reg_all = matchups_df[~matchups_df["is_playoff"] & ~matchups_df["is_consolation"] & ~matchups_df["is_championship"]].dropna(subset=["points_a", "points_b"])
        all_scores = pd.concat([
            reg_all[["season", "week", "team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
            reg_all[["season", "week", "team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
        ]).dropna()
        if not all_scores.empty:
            top = all_scores.loc[all_scores["pts"].idxmax()]
            awards["Highest Single-Week Score Ever"] = {
                "winner": top["owner"],
                "value": f"{top['pts']:.2f} pts",
                "description": f"Best single-week performance ever (Season {int(top['season'])}, Wk {int(top['week'])})",
                "runner_up": None,
            }
            # most blowout wins ever
            margins = reg_all.copy()
            margins["margin"] = (margins["points_a"] - margins["points_b"]).abs()
            blowouts = margins[margins["margin"] > 30]
            if not blowouts.empty:
                bk: dict[str, int] = {}
                for _, row in blowouts.iterrows():
                    winner_own = row["team_a_owner"] if row["winner_team_id"] == row["team_a_id"] else row["team_b_owner"]
                    bk[winner_own] = bk.get(winner_own, 0) + 1
                if bk:
                    best_bk = max(bk, key=bk.__getitem__)
                    awards["All-Time Blowout King"] = {
                        "winner": best_bk,
                        "value": f"{bk[best_bk]} blowout wins",
                        "description": "Most career wins by 30+ points",
                        "runner_up": None,
                    }
                lk: dict[str, float] = {}
                for _, row in blowouts.iterrows():
                    loser_own = row["team_b_owner"] if row["winner_team_id"] == row["team_a_id"] else row["team_a_owner"]
                    margin_val = float(row["margin"])
                    if loser_own not in lk or margin_val > lk[loser_own]:
                        lk[loser_own] = margin_val
                if lk:
                    biggest_lk = max(lk, key=lk.__getitem__)
                    awards["Most Lopsided Loss Ever"] = {
                        "winner": biggest_lk,
                        "value": f"Lost by {lk[biggest_lk]:.1f} pts",
                        "description": "Suffered the largest margin of defeat in league history",
                        "runner_up": None,
                    }
    except Exception:
        pass

    return awards
