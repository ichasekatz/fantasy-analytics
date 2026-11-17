"""Schedule Simulator: fairness analysis, win distributions, and schedule swaps."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.simulations import schedule_swap_wins
from style import inject_css
from utils import apply_league_filter


def render(conn) -> None:
    st.title("📅 Schedule Simulator")
    inject_css()

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())
    lid: str | None = st.session_state.get("selected_league_id")

    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    seasons = sorted(matchups_df["season"].dropna().unique(), reverse=True)

    tab1, tab2, tab3 = st.tabs(["Schedule Fairness", "Win Distribution", "What If?"])

    with tab1:
        _render_fairness(matchups_df, seasons, lid)

    with tab2:
        _render_distribution(matchups_df, seasons, lid)

    with tab3:
        _render_whatif(matchups_df, seasons, lid)


def _render_fairness(matchups_df: pd.DataFrame, seasons: list, lid: str | None) -> None:
    st.subheader("Schedule Fairness Analysis")
    st.caption("avg_simulated_wins = how many wins you'd average across every other team's schedule (keeping your actual scores).")

    sel = st.selectbox("Season", [str(s) for s in seasons], key="sched_fair_season")
    season = int(sel)

    with st.spinner("Running schedule simulations…"):
        swap = schedule_swap_wins(matchups_df, season, lid)

    if swap.empty:
        st.info("Not enough data for this season.")
        return

    swap["luck_delta"] = swap["actual_wins"] - swap["avg_simulated_wins"]
    swap_sorted = swap.sort_values("avg_simulated_wins", ascending=False).reset_index(drop=True)

    # Grouped bar chart
    melt = pd.melt(
        swap_sorted,
        id_vars=["owner"],
        value_vars=["actual_wins", "avg_simulated_wins"],
        var_name="type",
        value_name="wins",
    )
    melt["type"] = melt["type"].map({"actual_wins": "Actual Wins", "avg_simulated_wins": "Avg Simulated Wins"})
    fig = px.bar(
        melt,
        x="owner",
        y="wins",
        color="type",
        barmode="group",
        color_discrete_map={"Actual Wins": "#FF6B35", "Avg Simulated Wins": "#4A90D9"},
        labels={"owner": "Manager", "wins": "Wins", "type": ""},
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)

    # Table with color
    display = swap_sorted[["owner", "actual_wins", "avg_simulated_wins", "min_wins", "max_wins", "schedule_luck_rank", "luck_delta"]].rename(columns={
        "owner": "Manager",
        "actual_wins": "Actual W",
        "avg_simulated_wins": "Avg Sim W",
        "min_wins": "Min W",
        "max_wins": "Max W",
        "schedule_luck_rank": "Luck Rank",
        "luck_delta": "Luck Delta",
    })
    display["Avg Sim W"] = display["Avg Sim W"].round(1)
    display["Luck Delta"] = display["Luck Delta"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

    luckiest = swap_sorted.loc[swap_sorted["luck_delta"].idxmax(), "owner"]
    unluckiest = swap_sorted.loc[swap_sorted["luck_delta"].idxmin(), "owner"]
    c1, c2 = st.columns(2)
    c1.success(f"🍀 Luckiest: **{luckiest}** (actual wins exceeded sim avg by {swap_sorted['luck_delta'].max():.1f})")
    c2.error(f"💀 Unluckiest: **{unluckiest}** (actual wins below sim avg by {abs(swap_sorted['luck_delta'].min()):.1f})")


def _render_distribution(matchups_df: pd.DataFrame, seasons: list, lid: str | None) -> None:
    st.subheader("Win Distribution by Schedule")
    st.caption("How many wins each manager would have across all possible alternate schedules.")

    sel = st.selectbox("Season", [str(s) for s in seasons], key="sched_dist_season")
    season = int(sel)

    with st.spinner("Computing distributions…"):
        swap = schedule_swap_wins(matchups_df, season, lid)

    if swap.empty:
        st.info("Not enough data for this season.")
        return

    # Build long DataFrame for violin
    rows = []
    for _, row in swap.iterrows():
        try:
            dist = json.loads(row["wins_distribution"])
        except (json.JSONDecodeError, TypeError):
            dist = []
        for w in dist:
            rows.append({"Manager": row["owner"], "Wins": w})

    if not rows:
        st.info("No distribution data.")
        return

    dist_df = pd.DataFrame(rows)

    fig = px.violin(
        dist_df,
        x="Manager",
        y="Wins",
        box=True,
        points=False,
        color_discrete_sequence=["#4A90D9"],
    )

    # Overlay actual wins as orange dots
    for _, row in swap.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["owner"]],
            y=[row["actual_wins"]],
            mode="markers",
            marker=dict(color="#FF6B35", size=12, symbol="circle"),
            name=f"{row['owner']} actual",
            showlegend=False,
            hovertemplate=f"{row['owner']}: {row['actual_wins']} actual wins<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="Wins",
        xaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("🟠 Orange dots = actual wins. Violin = distribution of wins under all alternate schedules.")


def _render_whatif(matchups_df: pd.DataFrame, seasons: list, lid: str | None) -> None:
    st.subheader("What If? Schedule Swap")
    st.caption("How many wins would each manager have if they had played each other's opponents every week?")

    sel = st.selectbox("Season", [str(s) for s in seasons], key="sched_whatif_season")
    season = int(sel)

    with st.spinner("Computing swaps…"):
        swap = schedule_swap_wins(matchups_df, season, lid)

    if swap.empty or len(swap) < 2:
        st.info("Need at least 2 managers for this season.")
        return

    owners = swap["owner"].tolist()
    c1, c2 = st.columns(2)
    with c1:
        owner_a = st.selectbox("Manager A", owners, index=0, key="whatif_a")
    with c2:
        default_b = owners[1] if owners[1] != owner_a else owners[0]
        owner_b = st.selectbox("Manager B", [o for o in owners if o != owner_a], index=0, key="whatif_b")

    row_a = swap[swap["owner"] == owner_a].iloc[0]
    row_b = swap[swap["owner"] == owner_b].iloc[0]

    # Find win count for A on B's schedule and B on A's schedule
    # From the wins_distribution, the i-th entry corresponds to owner_b's schedule
    # We need to look up specific swap: A with B's opponents = A's sim wins when simulating B's schedule

    # Re-derive from raw logic: for owner_a using owner_b's schedule
    from fantasy.analytics.simulations import _regular_season, _team_weekly_scores, _weekly_matchups

    df = _regular_season(matchups_df, season, lid)
    if df.empty:
        st.info("No data.")
        return

    scores = _team_weekly_scores(df)
    owner_schedules: dict[str, dict[int, str]] = {}
    for week, pairs in _weekly_matchups(df).items():
        for oa, ob in pairs:
            owner_schedules.setdefault(oa, {})[week] = ob
            owner_schedules.setdefault(ob, {})[week] = oa

    def _swap_wins(owner: str, other: str) -> int:
        w = 0
        for week, opp_of_other in owner_schedules.get(other, {}).items():
            s_owner = scores.get(owner, {}).get(week, 0.0)
            s_opp = scores.get(opp_of_other, {}).get(week, 0.0)
            if s_owner > s_opp:
                w += 1
        return w

    a_on_b_schedule = _swap_wins(owner_a, owner_b)
    b_on_a_schedule = _swap_wins(owner_b, owner_a)

    st.divider()
    st.markdown(f"**If {owner_a} had played {owner_b}'s opponents each week (and vice versa):**")

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric(f"{owner_a} Actual", int(row_a["actual_wins"]))
    mc2.metric(f"{owner_a} on {owner_b}'s schedule", a_on_b_schedule, delta=int(a_on_b_schedule - row_a["actual_wins"]))
    mc3.metric(f"{owner_b} Actual", int(row_b["actual_wins"]))
    mc4.metric(f"{owner_b} on {owner_a}'s schedule", b_on_a_schedule, delta=int(b_on_a_schedule - row_b["actual_wins"]))
