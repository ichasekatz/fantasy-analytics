"""Manager comparison page: side-by-side stats, radar chart, weekly scoring, H2H matrix."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import career_standings, season_standings


@st.cache_data
def _career_df(_conn) -> pd.DataFrame:
    """Load career standings for all managers.

    Args:
        _conn: DuckDB connection (underscore prefix prevents st.cache_data hashing it).

    Returns:
        Career standings DataFrame.
    """
    df = _conn.execute("SELECT * FROM matchups").df()
    return career_standings(df)


def render(conn) -> None:
    """Render the Manager Comparison page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("📐 Manager Comparison")

    matchups_df = conn.execute("SELECT * FROM matchups").df()
    seasons_df = conn.execute("SELECT season, provider FROM seasons ORDER BY season").df()
    career = _career_df(conn)

    all_owners = sorted(matchups_df["team_a_owner"].dropna().unique().tolist()
                        + matchups_df["team_b_owner"].dropna().unique().tolist())
    all_owners = sorted(set(all_owners))

    col1, col2 = st.columns([3, 2])
    with col1:
        selected = st.multiselect("Select managers (up to 4)", all_owners, max_selections=4)
    with col2:
        provider_map = dict(zip(seasons_df["season"], seasons_df["provider"], strict=False))
        seasons = sorted(matchups_df["season"].unique())
        season_opts = ["All Seasons"] + [f"{s} ({provider_map.get(s,'?')})" for s in seasons]
        season_label = st.selectbox("Season", season_opts)

    selected_season: int | None = None
    if season_label != "All Seasons":
        selected_season = seasons[season_opts.index(season_label) - 1]

    if not selected:
        st.info("Select at least one manager above.")
        return

    st.divider()

    # --- Stats Comparison Table ---
    st.subheader("Stats Comparison")

    if selected_season is not None:
        s = season_standings(matchups_df, selected_season)
        stat_rows = []
        for mgr in selected:
            row = s[s["owner"] == mgr]
            if row.empty:
                continue
            r = row.iloc[0]
            stat_rows.append({
                "Manager": mgr,
                "W": int(r["wins"]),
                "L": int(r["losses"]),
                "Win%": round(r["win_pct"], 3),
                "PF": round(r["points_for"], 1),
                "PA": round(r["points_against"], 1),
                "Avg PF": round(r["avg_pf"], 1),
            })
    else:
        stat_rows = []
        for mgr in selected:
            row = career[career["owner"] == mgr]
            if row.empty:
                continue
            r = row.iloc[0]
            # Count championships
            champs = conn.execute("""
                SELECT COUNT(*) AS n FROM matchups
                WHERE is_championship = TRUE
                  AND ((team_a_owner = ? AND winner_team_id = team_a_id)
                    OR (team_b_owner = ? AND winner_team_id = team_b_id))
            """, [mgr, mgr]).fetchone()[0]
            stat_rows.append({
                "Manager": mgr,
                "Seasons": int(r["seasons_played"]),
                "W": int(r["wins"]),
                "L": int(r["losses"]),
                "Win%": round(r["win_pct"], 3),
                "Total PF": round(r["points_for"], 1),
                "Avg PF": round(r["avg_pf"], 1),
                "Championships": int(champs),
            })

    if stat_rows:
        stats_df = pd.DataFrame(stat_rows)
        st.dataframe(stats_df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Comparison CSV",
            stats_df.to_csv(index=False).encode("utf-8"),
            "manager_comparison.csv", "text/csv", key="dl_comp_stats",
        )
    else:
        st.info("No data found for selected managers in this season.")

    st.divider()

    # --- Radar Chart ---
    if len(selected) >= 2 and not career.empty:
        st.subheader("Multi-Dimension Radar")

        # Normalize metrics to 0-100 percentile across all managers
        def _percentile_rank(series: pd.Series) -> pd.Series:
            """Rank values as percentile 0-100."""
            return series.rank(pct=True) * 100

        radar_base = career.copy()
        radar_base["win_pct_pct"] = _percentile_rank(radar_base["win_pct"])
        radar_base["avg_pf_pct"] = _percentile_rank(radar_base["avg_pf"])

        # Consistency: inverse of std/mean (lower CV = more consistent = higher score)
        all_scores = pd.concat([
            matchups_df[["team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
            matchups_df[["team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
        ]).dropna()
        consistency = all_scores.groupby("owner")["pts"].agg(
            mean_pts="mean", std_pts="std"
        ).reset_index()
        consistency["cv"] = consistency["std_pts"] / consistency["mean_pts"].replace(0, pd.NA)
        consistency["consistency_pct"] = _percentile_rank(-consistency["cv"])  # lower CV = more consistent
        radar_base = radar_base.merge(consistency[["owner", "consistency_pct"]], on="owner", how="left")

        radar_cats = ["Win%", "Avg Score", "Consistency", "Seasons"]
        fig = go.Figure()
        for mgr in selected:
            row = radar_base[radar_base["owner"] == mgr]
            if row.empty:
                continue
            r = row.iloc[0]
            seasons_pct = _percentile_rank(radar_base["seasons_played"])[radar_base["owner"] == mgr].values
            vals = [
                float(r.get("win_pct_pct", 50)),
                float(r.get("avg_pf_pct", 50)),
                float(r.get("consistency_pct", 50)),
                float(seasons_pct[0]) if len(seasons_pct) else 50,
            ]
            vals_closed = vals + [vals[0]]
            cats_closed = radar_cats + [radar_cats[0]]
            fig.add_trace(go.Scatterpolar(r=vals_closed, theta=cats_closed, fill="toself", name=mgr))

        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("All axes are percentile ranks (0–100) relative to all managers in the database.")

    st.divider()

    # --- Weekly Scoring Over Time ---
    st.subheader("Weekly Scoring Over Time")
    score_rows = []
    for _, row in matchups_df.iterrows():
        for owner, pts in [(row["team_a_owner"], row["points_a"]), (row["team_b_owner"], row["points_b"])]:
            if owner in selected and pd.notna(pts):
                score_rows.append({
                    "owner": owner,
                    "season": row["season"],
                    "week": row.get("week"),
                    "pts": pts,
                })
    if score_rows:
        score_df = pd.DataFrame(score_rows).dropna(subset=["week"])
        score_df["week"] = pd.to_numeric(score_df["week"], errors="coerce")
        score_df = score_df.dropna(subset=["week"])
        score_df["week"] = score_df["week"].astype(int)
        score_df["season_week"] = score_df["season"].astype(str) + "-W" + score_df["week"].astype(str).str.zfill(2)
        score_df = score_df.sort_values(["season", "week"])

        import plotly.express as px
        fig2 = px.line(
            score_df, x="season_week", y="pts", color="owner",
            labels={"season_week": "Season-Week", "pts": "Points", "owner": "Manager"},
        )
        fig2.update_xaxes(tickangle=45)
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # --- Head-to-Head Matrix ---
    if len(selected) >= 2:
        st.subheader("Head-to-Head Matrix")
        h2h_matrix: dict[str, dict[str, str]] = {m: {m2: "—" for m2 in selected} for m in selected}

        for i, mgr_a in enumerate(selected):
            for mgr_b in selected[i + 1:]:
                h2h = matchups_df[
                    ((matchups_df["team_a_owner"] == mgr_a) & (matchups_df["team_b_owner"] == mgr_b))
                    | ((matchups_df["team_a_owner"] == mgr_b) & (matchups_df["team_b_owner"] == mgr_a))
                ]
                if h2h.empty:
                    continue
                wins_a = sum(
                    (r["winner_team_id"] == r["team_a_id"] and r["team_a_owner"] == mgr_a)
                    or (r["winner_team_id"] == r["team_b_id"] and r["team_b_owner"] == mgr_a)
                    for _, r in h2h.iterrows()
                )
                wins_b = len(h2h) - wins_a
                h2h_matrix[mgr_a][mgr_b] = f"{wins_a}–{wins_b}"
                h2h_matrix[mgr_b][mgr_a] = f"{wins_b}–{wins_a}"

        matrix_df = pd.DataFrame(h2h_matrix).T
        st.dataframe(matrix_df, use_container_width=True)
        st.caption("Format: wins–losses for the row manager against the column manager.")
        st.download_button(
            "⬇️ Download H2H Matrix CSV",
            matrix_df.to_csv().encode("utf-8"),
            "h2h_matrix.csv", "text/csv", key="dl_comp_h2h",
        )
