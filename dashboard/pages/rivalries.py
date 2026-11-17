"""Rivalry Dashboard: head-to-head stats, timelines, and rivalry matrix."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from fantasy.analytics.rivalries import all_rivalries, rivalry_stats, rivalry_timeline
from utils import apply_league_filter


def render(conn) -> None:
    """Render the Rivalry Dashboard page."""
    st.title("⚔️ Rivalry Dashboard")

    matchups_df = apply_league_filter(conn.execute("SELECT * FROM matchups").df())

    if matchups_df.empty:
        st.info("No matchup data available.")
        return

    all_owners = sorted(
        set(matchups_df["team_a_owner"].dropna()) | set(matchups_df["team_b_owner"].dropna())
    )

    tab_top, tab_spotlight, tab_matrix = st.tabs(
        ["🔥 Top Rivalries", "🔍 Rivalry Spotlight", "📊 Rivalry Matrix"]
    )

    with tab_top:
        _render_top_rivalries(matchups_df)

    with tab_spotlight:
        _render_spotlight(matchups_df, all_owners)

    with tab_matrix:
        _render_matrix(matchups_df, all_owners)


def _render_top_rivalries(matchups_df: pd.DataFrame) -> None:
    df = all_rivalries(matchups_df)
    if df.empty:
        st.info("Not enough matchup data to compute rivalries.")
        return

    st.subheader("Most Intense Rivalries")
    st.caption(
        "Rivalry intensity = total games × balance score. "
        "High intensity means frequent, competitive meetings."
    )

    display = df.copy()
    display["Record (A–B)"] = display.apply(
        lambda r: f"{int(r['a_wins'])}–{int(r['b_wins'])}" + (f"–{int(r['ties'])} T" if r["ties"] else ""),
        axis=1,
    )
    display["Avg Margin"] = display["avg_margin"].round(2)
    display["Closest"] = display["closest_game"].round(2)
    display["Intensity"] = display["rivalry_intensity"].round(1)

    out = display[["owner_a", "owner_b", "Record (A–B)", "total_games", "Avg Margin", "Closest", "Intensity"]].rename(
        columns={
            "owner_a": "Manager A",
            "owner_b": "Manager B",
            "total_games": "Games",
        }
    )
    st.dataframe(out, use_container_width=True, hide_index=True)

    # Bar chart of top 10
    top10 = display.head(10).copy()
    top10["Pair"] = top10["owner_a"] + " vs " + top10["owner_b"]
    fig = px.bar(
        top10,
        x="Intensity",
        y="Pair",
        orientation="h",
        color="Intensity",
        color_continuous_scale="Reds",
        labels={"Intensity": "Rivalry Intensity", "Pair": ""},
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        coloraxis_showscale=False,
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_spotlight(matchups_df: pd.DataFrame, all_owners: list[str]) -> None:
    if len(all_owners) < 2:
        st.info("Need at least two managers.")
        return

    col1, col2 = st.columns(2)
    with col1:
        owner_a = st.selectbox("Manager A", all_owners, key="riv_a")
    with col2:
        remaining = [o for o in all_owners if o != owner_a]
        owner_b = st.selectbox("Manager B", remaining, key="riv_b")

    stats = rivalry_stats(matchups_df, owner_a, owner_b)
    if stats["total_meetings"] == 0:
        st.info(f"No matchups found between {owner_a} and {owner_b}.")
        return

    a_wins, b_wins, ties = stats["all_time_record"]
    reg_a, reg_b, reg_t = stats["reg_season_record"]
    po_a, po_b, _ = stats["playoff_record"]

    st.subheader(f"{owner_a} vs {owner_b}")

    # Overall record banner
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{owner_a} Wins", a_wins)
    c2.metric("Ties", ties)
    c3.metric(f"{owner_b} Wins", b_wins)

    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Scoring**")
        st.metric(f"{owner_a} Total PF", f"{stats['total_pf_a']:.1f}")
        st.metric(f"{owner_b} Total PF", f"{stats['total_pf_b']:.1f}")
        st.metric("Avg Margin", f"{stats['avg_margin']:.2f} pts")
        st.metric("Closest Game", f"{stats['closest_game']:.2f} pts")
    with col_r:
        st.markdown("**Records**")
        st.metric("Regular Season", f"{reg_a}–{reg_b}" + (f"–{reg_t}" if reg_t else ""))
        st.metric("Playoff", f"{po_a}–{po_b}")
        st.metric(f"{owner_a} Best Streak", stats["most_consecutive_wins_a"])
        st.metric(f"{owner_b} Best Streak", stats["most_consecutive_wins_b"])

    # Championship meetings
    if stats["championship_matchups"]:
        st.divider()
        st.subheader("🏆 Championship Meetings")
        champ_df = pd.DataFrame(stats["championship_matchups"])
        champ_df = champ_df[["season", "pts_a", "pts_b", "winner", "margin"]].rename(
            columns={"pts_a": f"{owner_a} Pts", "pts_b": f"{owner_b} Pts"}
        )
        st.dataframe(champ_df, use_container_width=True, hide_index=True)

    # Timeline chart
    tl = rivalry_timeline(matchups_df, owner_a, owner_b)
    if not tl.empty:
        st.divider()
        st.subheader("Matchup History")
        tl["label"] = tl["season"].astype(str) + " W" + tl["week"].fillna(0).astype(int).astype(str)
        tl["color"] = tl["winner"].apply(
            lambda w: owner_a if w == owner_a else (owner_b if w == owner_b else "Tie")
        )

        fig = go.Figure()
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)

        for winner_label, color in [(owner_a, "#3b82f6"), (owner_b, "#ef4444"), ("Tie", "#94a3b8")]:
            mask = tl["color"] == winner_label
            subset = tl[mask]
            if subset.empty:
                continue
            fig.add_trace(go.Bar(
                x=subset["label"],
                y=subset["signed_margin"],
                name=f"{winner_label} wins",
                marker_color=color,
                hovertemplate="<b>%{x}</b><br>Margin: %{y:.2f} pts<extra></extra>",
            ))

        fig.update_layout(
            barmode="relative",
            xaxis_title="Season-Week",
            yaxis_title=f"← {owner_b} wins  |  {owner_a} wins →",
            legend_title="Winner",
            xaxis_tickangle=45,
            height=350,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Positive = {owner_a} won by that margin. Negative = {owner_b} won.")

        # Playoff games highlighted
        playoff_rows = tl[tl["is_playoff"]]
        if not playoff_rows.empty:
            st.markdown("**Playoff matchups** (included in chart above):")
            po_disp = playoff_rows[["season", "week", "pts_a", "pts_b", "winner", "margin"]].rename(
                columns={"pts_a": f"{owner_a}", "pts_b": f"{owner_b}"}
            )
            st.dataframe(po_disp, use_container_width=True, hide_index=True)


def _render_matrix(matchups_df: pd.DataFrame, all_owners: list[str]) -> None:
    st.subheader("Head-to-Head Win % Matrix")
    st.caption("Row manager's win % against column manager. — = no meetings.")

    if len(all_owners) < 2:
        st.info("Need at least two managers.")
        return

    # Build matrix
    matrix: dict[str, dict[str, str]] = {o: {} for o in all_owners}

    for i, owner_a in enumerate(all_owners):
        for owner_b in all_owners[i + 1:]:
            stats = rivalry_stats(matchups_df, owner_a, owner_b)
            if stats["total_meetings"] == 0:
                matrix[owner_a][owner_b] = "—"
                matrix[owner_b][owner_a] = "—"
                continue
            a_wins, b_wins, ties = stats["all_time_record"]
            total = stats["total_meetings"]
            pct_a = (a_wins + 0.5 * ties) / total
            pct_b = (b_wins + 0.5 * ties) / total
            matrix[owner_a][owner_b] = f"{pct_a:.0%}"
            matrix[owner_b][owner_a] = f"{pct_b:.0%}"

    for o in all_owners:
        matrix[o][o] = "—"

    matrix_df = pd.DataFrame(matrix, index=all_owners, columns=all_owners)
    st.dataframe(matrix_df, use_container_width=True)
    st.caption("Read as: row manager's win% against each column manager.")
