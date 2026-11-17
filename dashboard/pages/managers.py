"""Manager profile page: career stats, season-by-season breakdown, scoring distribution."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.cross_league import cross_league_standings
from fantasy.analytics.standings import career_standings, season_standings
from fantasy.identity.enrichment import enrich_matchups
from fantasy.identity.registry import load_registry

_missing_seasons = [2021]
_identity_path = Path(__file__).parents[2] / "data" / "identity" / "manager_aliases.json"


def render(conn) -> None:
    """Render the Manager Profiles page.

    Uses canonical display names when available. When "All Leagues" is selected,
    aggregates across every registered league.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("👤 Manager Profiles")

    league_id: str | None = st.session_state.get("selected_league_id")
    registry = load_registry(_identity_path)
    matchups_df = conn.execute("SELECT * FROM matchups").df()

    # Filter by league if one is selected
    if league_id and "league_id" in matchups_df.columns:
        filtered_df = matchups_df[matchups_df["league_id"] == league_id].copy()
    else:
        filtered_df = matchups_df.copy()

    enriched = enrich_matchups(filtered_df, registry)

    # Build manager display list: canonical names first, then raw owners not yet merged
    all_raw_owners = sorted(set(
        filtered_df["team_a_owner"].dropna().tolist()
        + filtered_df["team_b_owner"].dropna().tolist()
    ))

    # Canonical managers present in this dataset
    canonical_names = sorted(set(
        enriched["canonical_display_a"].dropna().tolist()
        + enriched["canonical_display_b"].dropna().tolist()
    ))
    # For selection, use canonical names (which fall back to raw name when unmerged)
    unique_managers = sorted(set(canonical_names))

    selected_manager = st.selectbox("Manager", unique_managers)

    # Career summary — use cross_league_standings if all leagues, else career_standings
    st.subheader("Career Statistics")
    if league_id is None:
        career = cross_league_standings(matchups_df, registry)
        owner_career = career[career["manager"] == selected_manager]
        if not owner_career.empty:
            row = owner_career.iloc[0]
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Seasons", int(row["seasons_played"]))
            c2.metric("Leagues", row["leagues"])
            c3.metric("W-L", f"{int(row['wins'])}-{int(row['losses'])}")
            c4.metric("Win%", f"{row['win_pct']:.3f}")
            c5.metric("Points For", f"{row['points_for']:.1f}")
            c6.metric("Avg PF/Game", f"{row['avg_pf']:.1f}")
        else:
            st.info("No career data found for this manager.")
    else:
        career = career_standings(filtered_df, league_id=league_id)
        # Match by canonical name or raw owner
        owner_career = career[career["owner"] == selected_manager]
        if not owner_career.empty:
            row = owner_career.iloc[0]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Seasons Played", int(row["seasons_played"]))
            c2.metric("Career W-L", f"{int(row['wins'])}-{int(row['losses'])}")
            c3.metric("Win%", f"{row['win_pct']:.3f}")
            c4.metric("Points For", f"{row['points_for']:.1f}")
            c5.metric("Avg PF/Game", f"{row['avg_pf']:.1f}")
        else:
            st.info("No career data found for this manager.")

    # Championships
    champ_q = """
        SELECT season, league_id FROM matchups
        WHERE is_championship = TRUE
          AND (team_a_owner = ? AND winner_team_id = team_a_id
               OR team_b_owner = ? AND winner_team_id = team_b_id)
        ORDER BY season
    """
    champs = conn.execute(champ_q, [selected_manager, selected_manager]).df()
    if not champs.empty:
        champ_strs = [
            f"{row['season']} ({row['league_id']})" if "league_id" in champs.columns else str(row["season"])
            for _, row in champs.iterrows()
        ]
        st.success(f"🏆 Championships: {', '.join(champ_strs)}")

    st.divider()

    # Season-by-season
    st.subheader("Season-by-Season")
    seasons = sorted(filtered_df["season"].unique())
    rows = []
    for season in seasons:
        s = season_standings(filtered_df, int(season), league_id)
        if s.empty:
            continue
        owner_row = s[s["owner"] == selected_manager]
        if owner_row.empty:
            continue
        r = owner_row.iloc[0]
        entry: dict = {
            "Season": int(season),
            "Team": r["team"],
            "W": int(r["wins"]),
            "L": int(r["losses"]),
            "Win%": f"{r['win_pct']:.3f}",
            "PF": round(r["points_for"], 2),
            "PA": round(r["points_against"], 2),
            "Finish": int(s.index[s["owner"] == selected_manager][0]) + 1,
        }
        if "league_id" in filtered_df.columns and league_id is None:
            entry["League"] = filtered_df[filtered_df["season"] == season]["league_id"].iloc[0]
        rows.append(entry)

    if rows:
        rows_df = pd.DataFrame(rows)
        st.dataframe(rows_df, use_container_width=True, hide_index=True)
    if _missing_seasons:
        st.caption(f"⚠️ Missing data for season(s): {', '.join(str(s) for s in _missing_seasons)}")

    st.divider()

    # Weekly scoring distribution
    st.subheader("Weekly Scoring Distribution")
    owner_scores = pd.concat([
        enriched[enriched["canonical_display_a"] == selected_manager][["season", "week", "points_a"]].rename(columns={"points_a": "pts"}),
        enriched[enriched["canonical_display_b"] == selected_manager][["season", "week", "points_b"]].rename(columns={"points_b": "pts"}),
    ]).dropna(subset=["pts"])

    if not owner_scores.empty:
        fig = px.histogram(
            owner_scores, x="pts", nbins=30,
            labels={"pts": "Weekly Points", "count": "Frequency"},
            color_discrete_sequence=["#1f77b4"],
        )
        fig.add_vline(x=owner_scores["pts"].mean(), line_dash="dash", annotation_text="Mean")
        st.plotly_chart(fig, use_container_width=True)

        season_avg = owner_scores.groupby("season")["pts"].mean().reset_index()
        fig2 = px.line(
            season_avg, x="season", y="pts", markers=True,
            labels={"season": "Season", "pts": "Avg Weekly Score"},
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No weekly scoring data available.")
