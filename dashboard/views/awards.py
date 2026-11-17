"""League Awards: automated annual awards + Hall of Shame badges."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.awards import all_time_awards, season_awards
from utils import apply_league_filter


# ---------------------------------------------------------------------------
# Hall of Shame: hardcoded badges for specific draft disasters
# ---------------------------------------------------------------------------

SHAME_BADGES: list[dict] = [
    # Cam Akers Award — given to every manager who ever drafted him
    {
        "emoji": "🐐",
        "award": "Cam Akers Award",
        "description": "Had the courage (or delusion) to draft Cam Akers.",
        "player": "Cam Akers",
        "recipients": [
            {"owner": "AnthonyKerr", "team": "Big Chungus", "season": 2020, "round": 8, "overall": 80},
            {"owner": "Sean Palumbo", "team": "Sean's Club of Fellas", "season": 2022, "round": 3, "overall": 29},
            {"owner": "Sean Palumbo", "team": "Sean's Club of Fellas", "season": 2023, "round": 6, "overall": 71},
            {"owner": "jbwallace", "team": "To Infinjty and Bijan", "season": 2023, "round": 6, "overall": 70},
        ],
    },
    # Marvin Harrison Jr. Badge — bad every year he was drafted
    {
        "emoji": "👻",
        "award": "Marvin Harrison Jr. Badge",
        "description": "Drafted MHJ. He was bad every single year.",
        "player": "Marvin Harrison Jr.",
        "recipients": [
            {"owner": "amerongill22", "team": "Dickallinyostomach", "season": 2024, "round": 2, "overall": 14},
            {"owner": "Sean Palumbo", "team": "SeanPalumbo52", "season": 2025, "round": 4, "overall": 44},
            {"owner": "jwearn", "team": "4 guys", "season": 2026, "round": 7, "overall": 80},
            {"owner": "juneeyeaa", "team": "Cuck Chair Connoisseur", "season": 2026, "round": 7, "overall": 63},
            {"owner": "jake griffith", "team": "Lamarvelous B*stards", "season": 2026, "round": 7, "overall": 62},
        ],
    },
    # Omarion Hampton Badge — 2026 only
    {
        "emoji": "🧊",
        "award": "Omarion Hampton Badge",
        "description": "Drafted Omarion Hampton in 2026. He was bad.",
        "player": "Omarion Hampton",
        "recipients": [
            {"owner": "Jonah Grettler", "team": "Oozma Kappa", "season": 2026, "round": 3, "overall": 31},
        ],
    },
]


def render(conn) -> None:
    """Render the Awards page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🏆 League Awards")

    lid: str | None = st.session_state.get("selected_league_id")
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    rosters_df = apply_league_filter(conn.execute("SELECT * FROM rosters").df())
    draft_df = conn.execute("SELECT * FROM draft_picks").df()
    if lid:
        draft_df = draft_df[draft_df["league_id"] == lid]

    tab_annual, tab_alltime, tab_shame = st.tabs(["Annual Awards", "All-Time Awards", "Hall of Shame"])

    with tab_annual:
        _render_annual(matchups_df, rosters_df, draft_df, lid)

    with tab_alltime:
        _render_alltime(matchups_df, rosters_df, draft_df, lid)

    with tab_shame:
        _render_shame(draft_df, rosters_df)


_AWARD_EMOJIS: dict[str, str] = {
    "Champion": "🏆",
    "Manager of the Year": "📈",
    "Regular Season Champion": "📈",
    "Highest Scorer": "🏹",
    "Last Place": "🪣",
    "Most Points Against": "🤕",
    "Luckiest Manager": "🍀",
    "Unluckiest Manager": "😤",
    "Scoring Machine": "💥",
    "Blowout King": "👑",
    "Glass Jaw": "💔",
    "Lineup Wizard": "🧙",
    "Bench Disaster": "🗑️",
    "Best Drafter": "🎯",
    "Worst Drafter": "😬",
    "Most Career Wins": "🏅",
    "Highest Career Win%": "📊",
    "Most Career Points": "💰",
    "Most Championships": "🏆",
    "Most Consecutive Championships": "🔥",
    "Longest Championship Drought": "🌵",
    "Luckiest Career": "🍀",
    "Unluckiest Career": "😤",
    "Highest Single-Week Score Ever": "💥",
    "All-Time Blowout King": "👑",
    "Most Lopsided Loss Ever": "💀",
}


def _render_awards_grid(awards: dict[str, dict]) -> None:
    """Render an awards dict as a card grid."""
    if not awards:
        st.info("Not enough data to compute awards.")
        return

    for name, data in awards.items():
        emoji = _AWARD_EMOJIS.get(name, "🥇")
        winner = data.get("winner", "?")
        value = data.get("value", "")
        desc = data.get("description", "")
        runner_up = data.get("runner_up")

        col1, col2 = st.columns([1, 4])
        with col1:
            st.markdown(f"### {emoji}")
        with col2:
            st.markdown(f"**{name}**")
            st.markdown(f"🥇 **{winner}** · `{value}`")
            if runner_up:
                st.caption(f"Runner-up: {runner_up}")
            st.caption(desc)
        st.divider()


def _render_annual(
    matchups_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_df: pd.DataFrame,
    lid: str | None,
) -> None:
    seasons = sorted(matchups_df["season"].dropna().unique().tolist(), reverse=True)
    if not seasons:
        st.info("No data available.")
        return

    selected_season = st.selectbox("Season", seasons, index=0, key="awards_season")

    with st.spinner("Computing awards..."):
        awards = season_awards(matchups_df, rosters_df, draft_df, int(selected_season), lid)

    _render_awards_grid(awards)


def _render_alltime(
    matchups_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    draft_df: pd.DataFrame,
    lid: str | None,
) -> None:
    st.subheader("All-Time Awards")
    st.caption("Career records across all seasons in the selected league view.")

    with st.spinner("Computing all-time awards..."):
        awards = all_time_awards(matchups_df, rosters_df, draft_df, lid)

    _render_awards_grid(awards)


def _render_shame(draft_df: pd.DataFrame, rosters_df: pd.DataFrame) -> None:
    st.subheader("🏅 Hall of Shame Badges")
    st.caption("Awarded for specific draft choices that live in infamy.")

    for badge in SHAME_BADGES:
        with st.expander(f"{badge['emoji']} **{badge['award']}** — {badge['player']}", expanded=True):
            st.caption(badge["description"])
            recs = badge["recipients"]

            # Deduplicate by (owner, season)
            seen: set[tuple] = set()
            unique_recs = []
            for r in recs:
                key = (r["owner"], r["season"])
                if key not in seen:
                    seen.add(key)
                    unique_recs.append(r)

            # Compute avg pts for this player per recipient from rosters
            player_name = badge["player"]
            player_rows = rosters_df[rosters_df["player"] == player_name] if not rosters_df.empty else pd.DataFrame()

            rows_out = []
            for r in unique_recs:
                entry = dict(r)
                if not player_rows.empty:
                    owner_col = "owner_name" if "owner_name" in player_rows.columns else "owner"
                    mask = (
                        (player_rows[owner_col] == r["owner"]) &
                        (player_rows["season"] == r["season"])
                    )
                    games = player_rows[mask]
                    if not games.empty and "points" in games.columns:
                        entry["avg_pts"] = round(games["points"].mean(), 2)
                        entry["games"] = len(games)
                    else:
                        entry["avg_pts"] = None
                        entry["games"] = 0
                rows_out.append(entry)

            df = pd.DataFrame(rows_out)
            rename = {
                "owner": "Manager",
                "team": "Team",
                "season": "Year",
                "round": "Round",
                "overall": "Pick #",
                "avg_pts": "Avg Pts/Game",
                "games": "Games",
            }
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            st.dataframe(df, use_container_width=True, hide_index=True)
