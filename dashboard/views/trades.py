"""Trade Lab: trade history, volume analytics, and waiver activity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.trade_eval import evaluate_all_trades, player_drop_regret, trade_leaderboard
from fantasy.analytics.transactions import trade_history, waiver_activity
from utils import apply_league_filter, resolve_owner_names


def _parse_trade_row(row: pd.Series) -> dict | None:
    """Parse one trade transaction into sent/received per party."""
    try:
        parties = json.loads(row["parties"]) if isinstance(row["parties"], str) else row["parties"]
        players = json.loads(row["players"]) if isinstance(row["players"], str) else row["players"]
    except (json.JSONDecodeError, TypeError):
        return None

    if not parties or len(parties) < 2:
        return None

    team_a = parties[0].get("team", parties[0].get("teamName", "?"))
    team_b = parties[1].get("team", parties[1].get("teamName", "?"))

    gave_a: list[str] = []
    gave_b: list[str] = []
    for p in (players or []):
        if not isinstance(p, dict):
            continue
        pname = p.get("player", p.get("name", "?"))
        from_team = p.get("from", {}).get("team", "")
        if from_team == team_a:
            gave_a.append(pname)
        elif from_team == team_b:
            gave_b.append(pname)

    return {
        "Season": row.get("season", "?"),
        "Week": row.get("week", "?"),
        "Team A": team_a,
        "A gave": ", ".join(gave_a) or "—",
        "Team B": team_b,
        "B gave": ", ".join(gave_b) or "—",
        "Players": len(players) if players else 0,
    }


def render(conn) -> None:
    """Render the Trade Lab page.

    Args:
        conn: Open DuckDB connection.
    """
    st.title("🔄 Trade Lab")

    transactions_df = conn.execute("SELECT * FROM transactions").df()
    lid: str | None = st.session_state.get("selected_league_id")

    if transactions_df.empty:
        st.info("No transaction data available.")
        return

    rosters_df = conn.execute("SELECT * FROM rosters").df()

    tab_history, tab_volume, tab_waiver, tab_grades, tab_regret = st.tabs([
        "Trade History", "Trade Volume", "Waiver Activity", "Trade Grades", "Drop Regret",
    ])

    with tab_history:
        _render_history(transactions_df, lid)

    with tab_volume:
        _render_volume(transactions_df, lid)

    with tab_waiver:
        _render_waiver(transactions_df, lid)

    with tab_grades:
        _render_grades(transactions_df, rosters_df, lid)

    with tab_regret:
        _render_drop_regret(transactions_df, rosters_df, lid)


def _render_history(transactions_df: pd.DataFrame, lid: str | None) -> None:
    trades_raw = transactions_df[transactions_df["type"] == "trade"].copy()
    if lid:
        trades_raw = trades_raw[trades_raw["league_id"] == lid]

    if trades_raw.empty:
        st.info("No trades found for this league.")
        return

    seasons = sorted(trades_raw["season"].dropna().unique(), reverse=True)
    all_teams: list[str] = []
    for _, row in trades_raw.iterrows():
        try:
            parties = json.loads(row["parties"]) if isinstance(row["parties"], str) else (row["parties"] or [])
            for p in parties:
                name = p.get("team", p.get("teamName", ""))
                if name:
                    all_teams.append(name)
        except (json.JSONDecodeError, TypeError):
            pass
    all_teams = sorted(set(all_teams))

    col1, col2 = st.columns(2)
    with col1:
        season_opts = ["All Seasons"] + [str(s) for s in seasons]
        season_sel = st.selectbox("Season", season_opts, key="trade_season")
    with col2:
        team_opts = ["All Teams"] + all_teams
        team_sel = st.selectbox("Team", team_opts, key="trade_team")

    filtered = trades_raw.copy()
    if season_sel != "All Seasons":
        filtered = filtered[filtered["season"] == int(season_sel)]

    parsed: list[dict] = []
    for _, row in filtered.iterrows():
        result = _parse_trade_row(row)
        if result:
            parsed.append(result)

    if not parsed:
        st.info("No trades to display for this selection.")
        return

    df = pd.DataFrame(parsed)

    if team_sel != "All Teams":
        mask = (df["Team A"] == team_sel) | (df["Team B"] == team_sel)
        df = df[mask]

    if df.empty:
        st.info(f"No trades found for {team_sel}.")
        return

    st.caption(f"{len(df)} trade(s)")
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_volume(transactions_df: pd.DataFrame, lid: str | None) -> None:
    trades_raw = transactions_df[transactions_df["type"] == "trade"].copy()
    if lid:
        trades_raw = trades_raw[trades_raw["league_id"] == lid]

    if trades_raw.empty:
        st.info("No trade data available.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Trades per Season")
        by_season = trades_raw.groupby("season").size().reset_index(name="Trades")
        fig = px.bar(by_season, x="season", y="Trades", labels={"season": "Season"})
        fig.update_layout(xaxis=dict(tickmode="array", tickvals=by_season["season"].tolist()))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Trades per Team")
        team_counts: dict[str, int] = {}
        for _, row in trades_raw.iterrows():
            try:
                parties = json.loads(row["parties"]) if isinstance(row["parties"], str) else (row["parties"] or [])
                seen_teams: set[str] = set()
                for p in parties:
                    name = p.get("team", p.get("teamName", ""))
                    if name and name not in seen_teams:
                        team_counts[name] = team_counts.get(name, 0) + 1
                        seen_teams.add(name)
            except (json.JSONDecodeError, TypeError):
                pass

        if team_counts:
            tc_df = pd.DataFrame(list(team_counts.items()), columns=["Team", "Trades"]).sort_values("Trades", ascending=True)
            fig2 = px.bar(tc_df, x="Trades", y="Team", orientation="h")
            fig2.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Most Traded Players")
    player_counts: dict[str, int] = {}
    for _, row in trades_raw.iterrows():
        try:
            players = json.loads(row["players"]) if isinstance(row["players"], str) else (row["players"] or [])
            for p in players:
                if isinstance(p, dict):
                    pname = p.get("player", p.get("name", ""))
                    if pname:
                        player_counts[pname] = player_counts.get(pname, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    if player_counts:
        pc_df = pd.DataFrame(list(player_counts.items()), columns=["Player", "Times Traded"]).sort_values("Times Traded", ascending=False).head(20)
        st.dataframe(pc_df, use_container_width=True, hide_index=True)


def _render_waiver(transactions_df: pd.DataFrame, lid: str | None) -> None:
    seasons = sorted(transactions_df["season"].dropna().unique(), reverse=True)
    if not seasons:
        st.info("No transaction data.")
        return

    season_opts = ["All Seasons"] + [str(s) for s in seasons]
    season_sel = st.selectbox("Season", season_opts, key="waiver_season")
    sel_season = None if season_sel == "All Seasons" else int(season_sel)

    activity = waiver_activity(transactions_df, season=sel_season, league_id=lid)
    activity = resolve_owner_names(activity)

    if activity.empty:
        st.info("No waiver/FA activity found.")
        return

    st.subheader("Waiver Activity by Manager")

    all_waiver_owners = sorted(activity["owner"].dropna().unique())
    sel_waiver_owners = st.multiselect("Filter managers", all_waiver_owners, default=all_waiver_owners, key="waiver_mgr")
    activity = activity[activity["owner"].isin(sel_waiver_owners)]

    display_cols = [c for c in ["owner", "season", "total_adds", "total_drops", "net_adds", "add_drop_transactions"] if c in activity.columns]
    rename = {
        "owner": "Manager", "season": "Season", "total_adds": "Adds",
        "total_drops": "Drops", "net_adds": "Net", "add_drop_transactions": "Add/Drops",
    }
    st.dataframe(
        activity[display_cols].rename(columns=rename).sort_values("Adds", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    if "total_adds" in activity.columns:
        fig = px.bar(
            activity.sort_values("total_adds", ascending=True),
            x="total_adds", y="owner", orientation="h",
            labels={"total_adds": "Total Adds", "owner": "Manager"},
            title="Total Waiver/FA Adds",
        )
        fig.update_layout(height=max(350, len(activity) * 35), yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)


def _player_detail_df(player_names: str, season: int, min_week: int, rosters_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-player stats table for players in a trade, rest-of-season from min_week."""
    names = [n.strip() for n in player_names.split(",") if n.strip() and n.strip() != "—"]
    if not names or rosters_df.empty:
        return pd.DataFrame()
    rdf = rosters_df.copy()
    rdf["week"] = pd.to_numeric(rdf["week"], errors="coerce")
    rdf["season"] = pd.to_numeric(rdf["season"], errors="coerce")
    rdf["points"] = pd.to_numeric(rdf["points"], errors="coerce").fillna(0)
    rows = []
    for pname in names:
        mask = (rdf["player"] == pname) & (rdf["season"] == season) & (rdf["week"] >= min_week)
        player_rows = rdf[mask]
        starters = player_rows[player_rows["starter"].fillna(False).astype(bool)]
        total = float(player_rows["points"].sum())
        started = float(starters["points"].sum())
        starts = int(starters.shape[0])
        avg = round(started / starts, 1) if starts > 0 else 0.0
        rows.append({
            "Player": pname,
            "Total Pts": round(total, 1),
            "Started Pts": round(started, 1),
            "Starts": starts,
            "Avg/Start": avg,
        })
    return pd.DataFrame(rows)


def _render_grades(transactions_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Trade Grades")
    st.caption("Grades based on actual started points from acquired vs. surrendered players, rest-of-season.")

    txn = transactions_df.copy()
    if lid:
        txn = txn[txn["league_id"] == lid]

    with st.spinner("Evaluating trades…"):
        eval_df = evaluate_all_trades(txn, rosters_df)

    if eval_df.empty:
        st.info("No trade data to evaluate.")
        return

    seasons = sorted(eval_df["season"].dropna().unique(), reverse=True)
    owners = sorted(eval_df["owner"].dropna().unique())

    col1, col2 = st.columns(2)
    with col1:
        season_sel = st.selectbox("Season", ["All"] + [str(s) for s in seasons], key="tg_season")
    with col2:
        owner_sel = st.selectbox("Manager", ["All"] + list(owners), key="tg_owner")

    filtered = eval_df.copy()
    if season_sel != "All":
        filtered = filtered[filtered["season"] == int(season_sel)]
    if owner_sel != "All":
        filtered = filtered[filtered["owner"] == owner_sel]

    lb = trade_leaderboard(filtered)
    if not lb.empty:
        st.subheader("Manager Trade Summary")
        all_lb_owners = sorted(lb["owner"].dropna().unique())
        sel_lb_owners = st.multiselect("Filter managers", all_lb_owners, default=all_lb_owners, key="tg_lb_mgr")
        lb_show = lb[lb["owner"].isin(sel_lb_owners)]
        fig_lb = px.bar(
            lb_show.sort_values("total_net_started_points", ascending=True),
            x="total_net_started_points", y="owner", orientation="h",
            labels={"total_net_started_points": "Net Started Pts", "owner": "Manager"},
            color="total_net_started_points",
            color_continuous_scale="RdYlGn",
            title="Net started points gained/lost via trades",
        )
        fig_lb.update_coloraxes(showscale=False)
        fig_lb.update_layout(height=max(350, len(lb_show) * 35), yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_lb, use_container_width=True)
        st.dataframe(lb_show.rename(columns={
            "owner": "Manager", "total_trades": "Trades", "trades_won": "Won",
            "trades_lost": "Lost", "trades_even": "Even",
            "total_net_started_points": "Net Pts", "avg_net_per_trade": "Avg Net/Trade",
        }), use_container_width=True, hide_index=True)
        st.divider()

    _VERDICT_ICON = {"Won": "🟢", "Lost": "🔴", "Even": "⚪"}

    for trade_id, grp in filtered.groupby("trade_id"):
        if len(grp) < 2:
            continue
        rows = grp.reset_index(drop=True)
        r0, r1 = rows.iloc[0], rows.iloc[1]
        v0 = _VERDICT_ICON.get(r0["verdict"], "")
        v1 = _VERDICT_ICON.get(r1["verdict"], "")
        label = (
            f"S{int(r0['season'])} Wk{int(r0['week'])}  |  "
            f"{r0['owner']} {v0} vs {r1['owner']} {v1}"
        )
        with st.expander(label):
            c1, c2 = st.columns(2)
            for col, r in [(c1, r0), (c2, r1)]:
                with col:
                    st.markdown(f"**{r['owner']}** — {_VERDICT_ICON.get(r['verdict'], '')} {r['verdict']}")
                    season_val = int(r['season'])
                    week_val = int(r['week'])
                    acq_df = _player_detail_df(r['players_acquired'], season_val, week_val, rosters_df)
                    sur_df = _player_detail_df(r['players_surrendered'], season_val, week_val, rosters_df)
                    if not acq_df.empty:
                        st.caption("▲ Acquired (rest-of-season from trade week)")
                        st.dataframe(acq_df, hide_index=True, use_container_width=True)
                    else:
                        st.markdown(f"Acquired: `{r['players_acquired']}`")
                    if not sur_df.empty:
                        st.caption("▼ Surrendered (rest-of-season from trade week)")
                        st.dataframe(sur_df, hide_index=True, use_container_width=True)
                    else:
                        st.markdown(f"Gave up: `{r['players_surrendered']}`")
                    st.markdown(
                        f"Started pts acquired: **{r['acq_started_points']:.1f}** ({r['acq_starter_weeks']} starts)  \n"
                        f"Started pts surrendered: **{r['sur_started_points']:.1f}** ({r['sur_starter_weeks']} starts)  \n"
                        f"Net started pts: **{r['net_started_points']:+.1f}**"
                    )


def _render_drop_regret(transactions_df: pd.DataFrame, rosters_df: pd.DataFrame, lid: str | None) -> None:
    st.subheader("Wall of Regret")
    st.caption("Players dropped before they produced meaningful fantasy value. Regret = started points scored after the drop.")

    txn = transactions_df.copy()
    if lid:
        txn = txn[txn["league_id"] == lid]

    seasons = sorted(txn["season"].dropna().unique(), reverse=True)
    season_sel = st.selectbox("Season", ["All"] + [str(s) for s in seasons], key="regret_season")
    sel_season = None if season_sel == "All" else int(season_sel)
    if sel_season:
        txn = txn[txn["season"] == sel_season]

    with st.spinner("Computing drop regret…"):
        regret_df = player_drop_regret(txn, rosters_df)
    regret_df = resolve_owner_names(regret_df)

    if regret_df.empty:
        st.info("No drop data found.")
        return

    top = regret_df[regret_df["regret_score"] > 0].nlargest(20, "regret_score").reset_index(drop=True)
    if top.empty:
        st.info("No regret-worthy drops found.")
        return

    _VERDICT_COLOR = {"High Regret": "🔴", "Medium Regret": "🟡", "Low Regret": "⚪"}

    display = top[["season", "week", "owner_drop", "dropped_player", "weeks_remaining",
                    "future_started_points", "future_started_weeks", "regret_score", "verdict"]].copy()
    display.insert(0, "#", range(1, len(display) + 1))
    display["verdict"] = display["verdict"].map(lambda v: f"{_VERDICT_COLOR.get(v, '')} {v}")
    display = display.rename(columns={
        "owner_drop": "Manager", "dropped_player": "Player",
        "season": "Season", "week": "Dropped Wk", "weeks_remaining": "Wks Left",
        "future_started_points": "Started Pts After", "future_started_weeks": "Starts After",
        "regret_score": "Regret Score", "verdict": "Verdict",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)
