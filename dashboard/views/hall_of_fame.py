"""League Museum: championship gallery, season timeline, franchise histories, draft boards."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.standings import career_standings, season_standings
from style import inject_css
from utils import apply_league_filter, is_dynasty_league, style_dataframe

_POS_COLORS = {
    "QB": "#E53E3E",
    "RB": "#38A169",
    "WR": "#3182CE",
    "TE": "#D69E2E",
    "K": "#805AD5",
    "DST": "#718096",
}


def render(conn) -> None:
    inject_css()
    st.title("🏛️ League Museum")

    lid = st.session_state.get("selected_league_id")
    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    draft_df = apply_league_filter(conn.execute("SELECT * FROM draft_picks ORDER BY season, overall").df())

    # apply_league_filter already applies the format (redraft_only/dynasty_only/all).
    # When format is "all", split further for separate sections.
    fmt = st.session_state.get("league_format", "redraft_only")
    if lid is None and fmt == "all" and "league_id" in matchups_df.columns:
        redraft_df = matchups_df[~matchups_df["league_id"].apply(is_dynasty_league)].copy()
        dynasty_df = matchups_df[matchups_df["league_id"].apply(is_dynasty_league)].copy()
    else:
        redraft_df = matchups_df
        dynasty_df = pd.DataFrame()

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏆 Championship Gallery",
        "📅 Season Timeline",
        "🏅 Franchise Histories",
        "🎭 Draft Boards",
    ])

    with tab1:
        _render_championship_gallery(redraft_df)
        if not dynasty_df.empty:
            with st.expander("🏰 Dynasty League Championships", expanded=False):
                _render_championship_gallery(dynasty_df)

    with tab2:
        _render_season_timeline(conn, redraft_df, dynasty_df)

    with tab3:
        _render_franchise_histories(conn, redraft_df)

    with tab4:
        _render_draft_boards(draft_df)


def _championship_rows(matchups_df: pd.DataFrame) -> pd.DataFrame:
    champs = matchups_df[matchups_df["is_championship"] == True].copy()
    if champs.empty:
        return pd.DataFrame()

    rows = []
    for _, row in champs.iterrows():
        if row["winner_team_id"] == row["team_a_id"]:
            champ, champ_team, champ_pts = row["team_a_owner"], row.get("team_a_name", ""), row["points_a"]
            runner, runner_pts = row["team_b_owner"], row["points_b"]
        else:
            champ, champ_team, champ_pts = row["team_b_owner"], row.get("team_b_name", ""), row["points_b"]
            runner, runner_pts = row["team_a_owner"], row["points_a"]
        rows.append({
            "season": int(row["season"]),
            "champion": champ,
            "champ_team": champ_team or champ,
            "champ_pts": round(float(champ_pts), 2),
            "runner_up": runner,
            "runner_pts": round(float(runner_pts), 2),
            "margin": round(abs(float(champ_pts) - float(runner_pts)), 2),
            "league_id": row.get("league_id", ""),
        })
    return pd.DataFrame(rows).sort_values("season")


def _render_championship_gallery(matchups_df: pd.DataFrame) -> None:
    st.subheader("🏆 Championship Gallery")

    champs = _championship_rows(matchups_df)
    if champs.empty:
        st.info("No championship data found.")
        return

    for _, row in champs.iterrows():
        dominant = row["margin"] > 20
        with st.container():
            cols = st.columns([1, 3, 2])
            with cols[0]:
                st.markdown(f"### {int(row['season'])}")
            with cols[1]:
                badge = " 👑 **DOMINANT**" if dominant else ""
                st.markdown(f"**🏆 {row['champion']}** — *{row['champ_team']}*{badge}")
                st.caption(f"def. {row['runner_up']} · {row['champ_pts']} – {row['runner_pts']} · margin {row['margin']}")
            with cols[2]:
                st.metric("Winning Score", row["champ_pts"])
        st.divider()

    st.subheader("Championship Counts")
    counts = champs["champion"].value_counts().reset_index()
    counts.columns = ["Manager", "Championships"]
    fig = px.bar(
        counts.sort_values("Championships"),
        x="Championships", y="Manager", orientation="h",
        color="Championships",
        color_continuous_scale=["#F7C59F", "#FF6B35"],
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)


def _render_season_timeline(conn, matchups_df: pd.DataFrame, dynasty_df: pd.DataFrame | None = None) -> None:
    st.subheader("📅 Season Timeline")

    seasons = sorted(matchups_df["season"].dropna().unique())
    if not seasons:
        st.info("No season data.")
    else:
        champ_map = {}
        for _, row in _championship_rows(matchups_df).iterrows():
            champ_map[int(row["season"])] = row["champion"]

        all_scores = pd.concat([
            matchups_df[["season", "week", "team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
            matchups_df[["season", "week", "team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
        ]).dropna(subset=["pts"])

        for s in reversed(seasons):
            s = int(s)
            season_scores = all_scores[all_scores["season"] == s]
            _sd = matchups_df[matchups_df["season"] == s]
            teams = len(set(_sd["team_a_owner"].dropna().tolist() + _sd["team_b_owner"].dropna().tolist()))
            champion = champ_map.get(s, "—")
            top_scorer = season_scores.loc[season_scores["pts"].idxmax()] if not season_scores.empty else None

            with st.expander(f"**{s}** — 🏆 {champion} · {teams} teams", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("Champion", champion)
                if top_scorer is not None:
                    try:
                        pts_val = float(top_scorer["pts"])
                        c2.metric("Best Single Game", f"{pts_val:.1f} pts")
                        c3.metric("Best Scorer", str(top_scorer["owner"]))
                    except (KeyError, TypeError, ValueError):
                        pass

                lid: str | None = st.session_state.get("selected_league_id")
                standings = season_standings(matchups_df, s, lid)
                if not standings.empty:
                    top3 = standings.head(3)[["owner", "total_wins", "total_losses", "points_for"]].rename(columns={
                        "owner": "Manager", "total_wins": "W", "total_losses": "L", "points_for": "PF"
                    })
                    top3["PF"] = top3["PF"].round(1)
                    st.caption("Top 3 finishers:")
                    st.dataframe(style_dataframe(top3, higher_is_better=["W", "PF"], lower_is_better=["L"]), use_container_width=True, hide_index=True)

    # Dynasty section
    if dynasty_df is not None and not dynasty_df.empty:
        st.divider()
        st.subheader("🏰 Dynasty League Timeline")
        dynasty_seasons = sorted(dynasty_df["season"].dropna().unique())
        dynasty_champ_map = {}
        for _, row in _championship_rows(dynasty_df).iterrows():
            dynasty_champ_map[int(row["season"])] = row["champion"]
        dynasty_scores = pd.concat([
            dynasty_df[["season", "week", "team_a_owner", "points_a"]].rename(columns={"team_a_owner": "owner", "points_a": "pts"}),
            dynasty_df[["season", "week", "team_b_owner", "points_b"]].rename(columns={"team_b_owner": "owner", "points_b": "pts"}),
        ]).dropna(subset=["pts"])
        for s in reversed(dynasty_seasons):
            s = int(s)
            champion = dynasty_champ_map.get(s, "—")
            _dsd = dynasty_df[dynasty_df["season"] == s]
            teams = len(set(_dsd["team_a_owner"].dropna().tolist() + _dsd["team_b_owner"].dropna().tolist()))
            with st.expander(f"**{s}** — 🏆 {champion} · {teams} teams (dynasty)", expanded=False):
                st.caption("Dynasty league season.")


def _render_franchise_histories(conn, matchups_df: pd.DataFrame) -> None:
    st.subheader("🏅 All-Time Franchise Histories")

    if matchups_df.empty:
        st.info("No data.")
        return

    champ_map: dict[str, int] = {}
    for _, row in _championship_rows(matchups_df).iterrows():
        c = row["champion"]
        champ_map[c] = champ_map.get(c, 0) + 1

    # Playoff appearances: seasons where manager appeared in a playoff matchup
    playoff_df = matchups_df[matchups_df["is_playoff"].fillna(False) | matchups_df["is_championship"].fillna(False)]
    playoff_owners = set(playoff_df["team_a_owner"].dropna().tolist() + playoff_df["team_b_owner"].dropna().tolist())
    playoff_by_owner: dict[str, set] = {}
    for _, row in playoff_df.iterrows():
        for o in [row["team_a_owner"], row["team_b_owner"]]:
            if o:
                playoff_by_owner.setdefault(o, set()).add(int(row["season"]))

    lid: str | None = st.session_state.get("selected_league_id")
    career = career_standings(matchups_df, league_id=lid)
    if career.empty:
        st.info("No career data.")
        return

    # Compute avg PF rank and avg PA rank per manager across all seasons
    all_seasons = sorted(matchups_df["season"].dropna().unique())
    pf_rank_sums: dict[str, list[float]] = {}
    pa_rank_sums: dict[str, list[float]] = {}
    for s in all_seasons:
        st_df = season_standings(matchups_df, int(s), lid)
        if st_df.empty:
            continue
        n = len(st_df)
        if n < 2:
            continue
        pf_ranks = st_df["points_for"].fillna(0).rank(ascending=False, method="min").astype(int)
        pa_ranks = st_df["points_against"].fillna(0).rank(ascending=True, method="min").astype(int)
        for i, row in st_df.iterrows():
            owner = row["owner"]
            # 12-team scale: rank 1 = best, rank 12 = worst
            pf_pct = 1 + (int(pf_ranks.loc[i]) - 1) / max(n - 1, 1) * 11
            pa_pct = 1 + (int(pa_ranks.loc[i]) - 1) / max(n - 1, 1) * 11
            pf_rank_sums.setdefault(owner, []).append(pf_pct)
            pa_rank_sums.setdefault(owner, []).append(pa_pct)

    rows = []
    for _, r in career.iterrows():
        owner = r["owner"]
        playoffs = len(playoff_by_owner.get(owner, set()))
        pf_pcts = pf_rank_sums.get(owner, [])
        pa_pcts = pa_rank_sums.get(owner, [])
        rows.append({
            "Manager": owner,
            "Seasons": int(r["seasons_played"]),
            "W": int(r["h2h_wins"]),
            "L": int(r["h2h_losses"]),
            "Win%": round(float(r["h2h_win_pct"]), 3),
            "Avg PF Rank": round(sum(pf_pcts) / len(pf_pcts), 1) if pf_pcts else None,
            "Avg PA Rank": round(sum(pa_pcts) / len(pa_pcts), 1) if pa_pcts else None,
            "Playoffs": playoffs,
            "Championships": champ_map.get(owner, 0),
        })

    df = pd.DataFrame(rows).sort_values("W", ascending=False)
    min_seasons_filter = st.session_state.get("min_seasons_played", 1)
    if min_seasons_filter > 1:
        df = df[df["Seasons"] >= min_seasons_filter].reset_index(drop=True)
    styled = style_dataframe(
        df,
        higher_is_better=["W", "Win%", "Playoffs", "Championships", "Seasons"],
        lower_is_better=["L", "Avg PF Rank", "Avg PA Rank"],
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.divider()
    owners = sorted(career["owner"].dropna().unique())
    sel = st.selectbox("Manager detail view", owners, key="hof_manager")

    lid2: str | None = st.session_state.get("selected_league_id")
    seasons = sorted(matchups_df["season"].unique())
    history_rows = []
    champ_seasons = {
        int(cr["season"]) for _, cr in _championship_rows(matchups_df).iterrows()
        if cr["champion"] == sel
    }
    for s in seasons:
        standings = season_standings(matchups_df, int(s), lid2)
        if standings.empty:
            continue
        idx = standings.index[standings["owner"] == sel].tolist()
        if not idx:
            continue
        rank = idx[0] + 1
        r = standings.iloc[idx[0]]
        n = len(standings)
        # PF/PA rank normalized to [0,1] like the avg rank tables
        pf_ranks = standings["points_for"].fillna(0).rank(ascending=False, method="min").astype(int)
        pa_ranks = standings["points_against"].fillna(0).rank(ascending=True, method="min").astype(int)
        pf_r = int(pf_ranks.iloc[idx[0]])
        pa_r = int(pa_ranks.iloc[idx[0]])
        pf_pct = round(1.0 - (pf_r - 1) / max(n - 1, 1), 3)
        pa_pct = round(1.0 - (pa_r - 1) / max(n - 1, 1), 3)
        history_rows.append({
            "Season": int(s),
            "Team": r.get("team", ""),
            "W": int(r["total_wins"]),
            "L": int(r["total_losses"]),
            "PF": round(float(r["points_for"]), 1),
            "PA": round(float(r["points_against"]), 1),
            "PF Rank": pf_pct,
            "PA Rank": pa_pct,
            "Finish": rank,
            "Champion": "🏆" if int(s) in champ_seasons else "",
        })

    if history_rows:
        st.subheader(f"{sel} — Season History")
        hist_df = pd.DataFrame(history_rows)
        styled_hist = style_dataframe(
            hist_df,
            higher_is_better=["W", "PF", "PF Rank", "PA Rank"],
            lower_is_better=["L", "PA", "Finish"],
        )
        st.dataframe(styled_hist, use_container_width=True, hide_index=True)
        st.caption("PF Rank / PA Rank: 1.0 = best in league that season, 0.0 = worst. Normalized for field size.")


def _render_draft_boards(draft_df: pd.DataFrame) -> None:
    st.subheader("🎭 Historical Draft Boards")

    if draft_df.empty:
        st.info("No draft data.")
        return

    seasons = sorted(draft_df["season"].unique(), reverse=True)
    sel_season = st.selectbox("Season", seasons, key="hof_draft_season")
    df = draft_df[draft_df["season"] == sel_season].copy()

    if df.empty:
        st.info("No draft data for this season.")
        return

    num_rounds = int(df["round"].max())
    owners_ordered = df.sort_values("overall").groupby("round").apply(
        lambda g: g.sort_values("overall")["owner_name"].tolist()
    ).iloc[0] if num_rounds > 0 else []

    # Build pivot: index=round, columns=pick_in_round, values=cell text
    df["pick_in_round"] = df.groupby("round")["overall"].rank(method="first").astype(int)
    df["cell"] = df.apply(
        lambda r: f"**{r['owner_name']}**\n{r['player']} ({r['position']})" + (" 🔑" if r.get("keeper") else ""),
        axis=1,
    )

    pivot = df.pivot(index="round", columns="pick_in_round", values="cell").fillna("")

    # Color by position using a heatmap-style approach — render as styled HTML table
    pos_color_map = {
        "QB": "#742A2A", "RB": "#1C4532", "WR": "#1A365D",
        "TE": "#744210", "K": "#322659", "DST": "#2D3748",
    }

    def _cell_color(row_idx: int, col_idx: int) -> str:
        try:
            pos = df[(df["round"] == row_idx) & (df["pick_in_round"] == col_idx)]["position"].iloc[0]
            return pos_color_map.get(pos, "#2D3748")
        except IndexError:
            return "#1A202C"

    max_picks = int(df["pick_in_round"].max())
    html_rows = []
    for rnd in range(1, num_rounds + 1):
        cells = []
        for pick in range(1, max_picks + 1):
            text = pivot.loc[rnd, pick] if rnd in pivot.index and pick in pivot.columns else ""
            bg = _cell_color(rnd, pick)
            cells.append(
                f'<td style="background:{bg};color:#F0F4F8;padding:6px 8px;font-size:0.75rem;'
                f'border:1px solid #2D3550;min-width:100px;vertical-align:top;white-space:pre-wrap">'
                f'{text.replace("**", "").replace("*", "")}</td>'
            )
        html_rows.append(f'<tr><td style="background:#0E1117;color:#8892A4;padding:4px 8px;font-weight:700">R{rnd}</td>' + "".join(cells) + "</tr>")

    table_html = (
        '<div style="overflow-x:auto">'
        '<table style="border-collapse:collapse;width:max-content">'
        "<thead><tr>"
        '<th style="background:#0E1117;padding:4px 8px"></th>'
        + "".join(f'<th style="background:#0E1117;color:#8892A4;padding:4px 8px;font-size:0.75rem">Pick {p}</th>' for p in range(1, max_picks + 1))
        + "</tr></thead><tbody>"
        + "".join(html_rows)
        + "</tbody></table></div>"
    )

    st.markdown(table_html, unsafe_allow_html=True)

    st.divider()
    st.caption("Position colors: 🔴 QB · 🟢 RB · 🔵 WR · 🟡 TE · 🟣 K · ⚫ DST · 🔑 Keeper")
