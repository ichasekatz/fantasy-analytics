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
from utils import apply_league_filter, style_dataframe


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
    styled_out = style_dataframe(out, higher_is_better=["Games", "Intensity"], lower_is_better=["Avg Margin"])
    st.dataframe(styled_out, use_container_width=True, hide_index=True)

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
        styled_champ = style_dataframe(champ_df, higher_is_better=["margin"], lower_is_better=[])
        st.dataframe(styled_champ, use_container_width=True, hide_index=True)

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
            st.dataframe(style_dataframe(po_disp, higher_is_better=["margin"]), use_container_width=True, hide_index=True)


def _render_matrix(matchups_df: pd.DataFrame, all_owners: list[str]) -> None:
    import numpy as np
    import plotly.graph_objects as go

    st.subheader("Head-to-Head Win % Matrix")
    st.caption("Row manager's win % against column manager. Gray = no meetings. Green > 50%, Red < 50%.")

    if len(all_owners) < 2:
        st.info("Need at least two managers.")
        return

    n = len(all_owners)
    num_matrix = [[float("nan")] * n for _ in range(n)]
    text_matrix = [[""] * n for _ in range(n)]

    # Cache all pair stats to avoid double-querying
    pair_cache: dict[tuple[int, int], dict] = {}
    for i in range(n):
        for j in range(i + 1, n):
            pair_cache[(i, j)] = rivalry_stats(matchups_df, all_owners[i], all_owners[j])

    for i in range(n):
        for j in range(n):
            if i == j:
                text_matrix[i][j] = "—"
                continue
            lo, hi = (i, j) if i < j else (j, i)
            stats = pair_cache[(lo, hi)]
            total = stats["total_meetings"]
            if total == 0:
                text_matrix[i][j] = "—"
                continue
            a_wins, b_wins, ties = stats["all_time_record"]
            # a is always all_owners[lo]; row i wins when i == lo → a_wins else b_wins
            if i == lo:
                pct = (a_wins + 0.5 * ties) / total
            else:
                pct = (b_wins + 0.5 * ties) / total
            num_matrix[i][j] = pct
            text_matrix[i][j] = f"{pct:.0%}<br>({int(total)}g)"

    z = [[v if not (isinstance(v, float) and v != v) else None for v in row] for row in num_matrix]

    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=all_owners,
        y=all_owners,
        text=text_matrix,
        texttemplate="%{text}",
        colorscale=[
            [0.0, "#ef4444"],    # 0% = red
            [0.5, "#fbbf24"],    # 50% = yellow
            [1.0, "#22c55e"],    # 100% = green
        ],
        zmid=0.5,
        zmin=0.0,
        zmax=1.0,
        colorbar={"title": "Win%", "tickformat": ".0%"},
        hoverongaps=False,
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(400, n * 45),
        xaxis={"side": "top", "tickangle": -30},
        font={"size": 11},
        margin={"t": 120, "l": 10, "r": 10, "b": 10},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Read as: row manager's win% against each column manager. Number in parentheses = total games.")
