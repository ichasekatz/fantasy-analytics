"""Bad Beat Index: ranking the most devastating fantasy losses."""

from __future__ import annotations

import numpy as np
import pandas as pd


def bad_beat_index(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Score each loss by devastation level.

    Bad Beat Score = (loser_percentile*40 + winner_outlier*30 + margin_tightness*20) * playoff_weight

    Returns one row per loss, sorted by bad_beat_score desc with rank column.
    """
    if matchups_df.empty:
        return pd.DataFrame()

    all_scores = pd.concat([
        matchups_df[["points_a"]].rename(columns={"points_a": "pts"}),
        matchups_df[["points_b"]].rename(columns={"points_b": "pts"}),
    ]).dropna()

    score_mean = float(all_scores["pts"].mean())
    score_std = float(all_scores["pts"].std())
    score_sorted = all_scores["pts"].sort_values().values

    def _pct(score: float) -> float:
        return float(np.searchsorted(score_sorted, score) / len(score_sorted))

    rows = []
    for _, row in matchups_df.iterrows():
        pa, pb = row.get("points_a"), row.get("points_b")
        if pd.isna(pa) or pd.isna(pb) or pa == pb:
            continue

        if pa < pb:
            loser, loser_team, loser_score = row["team_a_owner"], row.get("team_a_name", ""), float(pa)
            winner, winner_team, winner_score = row["team_b_owner"], row.get("team_b_name", ""), float(pb)
        else:
            loser, loser_team, loser_score = row["team_b_owner"], row.get("team_b_name", ""), float(pb)
            winner, winner_team, winner_score = row["team_a_owner"], row.get("team_a_name", ""), float(pa)

        margin = winner_score - loser_score
        loser_pct = _pct(loser_score)
        winner_sigma = max(0.0, (winner_score - score_mean) / score_std) if score_std > 0 else 0.0
        is_playoff = bool(row.get("is_playoff", False))
        is_champ = bool(row.get("is_championship", False))

        playoff_w = 1.5 if (is_playoff or is_champ) else 1.0
        margin_tight = max(0.0, 1.0 - (margin / 50.0))
        winner_norm = min(1.0, winner_sigma / 3.0)

        beat_score = (loser_pct * 40.0 + winner_norm * 30.0 + margin_tight * 20.0) * playoff_w

        rows.append({
            "season": row.get("season"),
            "week": row.get("week"),
            "league_id": row.get("league_id", ""),
            "loser": loser,
            "loser_team": loser_team,
            "loser_score": round(loser_score, 2),
            "winner": winner,
            "winner_team": winner_team,
            "winner_score": round(winner_score, 2),
            "margin": round(margin, 2),
            "loser_percentile": round(loser_pct * 100, 1),
            "winner_outlier_sigma": round(winner_sigma, 2),
            "is_playoff": is_playoff,
            "is_championship": is_champ,
            "bad_beat_score": round(beat_score, 1),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("bad_beat_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df
