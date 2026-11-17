"""Custom Analytics — SQL query builder, saved queries, metric playground."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

try:
    from style import inject_css
except ImportError:
    def inject_css() -> None:
        pass

_SCHEMA_HELP = """
**Available tables:**
- `matchups` — season, week, team_a_owner, team_b_owner, points_a, points_b, is_playoff, is_championship, league_id
- `rosters` — season, week, owner_name, team_name, player, position, starter, points, league_id
- `draft_picks` — season, overall, round, owner_name, player, position, keeper, league_id
- `transactions` — season, week, type, parties, players, league_id
- `seasons` — season, provider, league_id
- `owners` — owner_id, owner_name, league_id
"""

_EXAMPLE_QUERIES = {
    "Top weekly scores ever": """
SELECT team_a_owner AS owner, season, week, points_a AS score
FROM matchups WHERE points_a IS NOT NULL
UNION ALL
SELECT team_b_owner, season, week, points_b
FROM matchups WHERE points_b IS NOT NULL
ORDER BY score DESC LIMIT 20
""".strip(),

    "Manager win% by season": """
WITH all_games AS (
  SELECT team_a_owner AS owner, season,
         CASE WHEN winner_team_id = team_a_id THEN 1 ELSE 0 END AS won
  FROM matchups WHERE team_a_owner IS NOT NULL
  UNION ALL
  SELECT team_b_owner, season,
         CASE WHEN winner_team_id = team_b_id THEN 1 ELSE 0 END AS won
  FROM matchups WHERE team_b_owner IS NOT NULL
)
SELECT owner, season,
       COUNT(*) AS games,
       SUM(won) AS wins,
       ROUND(AVG(won) * 100, 1) AS win_pct
FROM all_games
GROUP BY owner, season
ORDER BY season, win_pct DESC
""".strip(),

    "Best draft rounds by VORP": """
SELECT d.round,
       COUNT(*) AS picks,
       ROUND(AVG(r.points), 1) AS avg_started_pts,
       ROUND(SUM(r.points), 1) AS total_started_pts
FROM draft_picks d
JOIN (
  SELECT season, league_id, player, SUM(points) AS points
  FROM rosters WHERE starter = TRUE
  GROUP BY season, league_id, player
) r ON d.player = r.player AND d.season = r.season AND d.league_id = r.league_id
WHERE d.keeper = FALSE
GROUP BY d.round
ORDER BY avg_started_pts DESC
""".strip(),

    "Most active traders": """
SELECT
  parties_parsed.owner,
  COUNT(*) AS trades
FROM transactions t,
  LATERAL (
    SELECT UNNEST(json_extract_string(t.parties, '$[*].team')) AS owner
  ) parties_parsed
WHERE t.type = 'trade'
GROUP BY parties_parsed.owner
ORDER BY trades DESC
LIMIT 15
""".strip(),

    "Weekly scoring variance by manager": """
WITH scores AS (
  SELECT team_a_owner AS owner, points_a AS pts FROM matchups WHERE points_a IS NOT NULL
  UNION ALL
  SELECT team_b_owner, points_b FROM matchups WHERE points_b IS NOT NULL
)
SELECT owner,
       COUNT(*) AS weeks,
       ROUND(AVG(pts), 1) AS avg_score,
       ROUND(STDDEV(pts), 1) AS std_dev,
       ROUND(MIN(pts), 1) AS min_score,
       ROUND(MAX(pts), 1) AS max_score
FROM scores
GROUP BY owner
ORDER BY std_dev DESC
""".strip(),
}


def render(conn) -> None:
    inject_css()
    st.title("🔬 Custom Analytics")
    st.caption("Run your own SQL queries against the full database. All queries are read-only.")

    tab1, tab2 = st.tabs(["Query Builder", "Schema Reference"])

    with tab1:
        _render_query_builder(conn)

    with tab2:
        st.markdown(_SCHEMA_HELP)
        st.divider()
        st.subheader("Example Queries")
        for name, sql in _EXAMPLE_QUERIES.items():
            with st.expander(name):
                st.code(sql, language="sql")


def _render_query_builder(conn) -> None:
    if "saved_queries" not in st.session_state:
        st.session_state["saved_queries"] = {}
    if "last_query" not in st.session_state:
        st.session_state["last_query"] = ""

    col1, col2 = st.columns([3, 1])

    with col2:
        example_pick = st.selectbox(
            "Load example",
            ["(blank)"] + list(_EXAMPLE_QUERIES.keys()),
            key="cq_example",
        )
        if example_pick != "(blank)":
            st.session_state["last_query"] = _EXAMPLE_QUERIES[example_pick]

        saved_names = list(st.session_state["saved_queries"].keys())
        if saved_names:
            saved_pick = st.selectbox("Load saved", ["(none)"] + saved_names, key="cq_saved")
            if saved_pick != "(none)":
                st.session_state["last_query"] = st.session_state["saved_queries"][saved_pick]

    with col1:
        query = st.text_area(
            "SQL Query",
            value=st.session_state.get("last_query", ""),
            height=180,
            key="cq_input",
            placeholder="SELECT * FROM matchups LIMIT 10",
        )

    col_run, col_save, col_clear = st.columns([2, 2, 1])

    with col_run:
        run = st.button("▶ Run Query", type="primary", use_container_width=True)

    with col_save:
        save_name = st.text_input("Save as", placeholder="Query name", key="cq_save_name")
        if st.button("💾 Save", use_container_width=True) and save_name and query.strip():
            st.session_state["saved_queries"][save_name] = query
            st.success(f"Saved: {save_name}")

    with col_clear:
        if st.button("🗑️", help="Clear"):
            st.session_state["last_query"] = ""
            st.rerun()

    if not run or not query.strip():
        return

    st.session_state["last_query"] = query

    # Safety: block mutating statements
    q_upper = query.strip().upper()
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "ALTER ", "TRUNCATE "):
        if q_upper.startswith(forbidden) or f" {forbidden}" in q_upper:
            st.error(f"Mutating queries not allowed: {forbidden.strip()}")
            return

    with st.spinner("Running…"):
        try:
            result = conn.execute(query).df()
        except Exception as exc:
            st.error(f"Query error: {exc}")
            return

    if result.empty:
        st.info("Query returned 0 rows.")
        return

    st.caption(f"{len(result)} row(s) · {len(result.columns)} column(s)")
    st.dataframe(result, use_container_width=True, hide_index=True)

    # Auto-chart: if 2 columns and second is numeric, offer bar chart
    if len(result.columns) >= 2:
        num_cols = result.select_dtypes("number").columns.tolist()
        str_cols = result.select_dtypes(["object", "string"]).columns.tolist()
        if num_cols and str_cols:
            chart_x = st.selectbox("Chart X axis", str_cols, key="cq_cx")
            chart_y = st.selectbox("Chart Y axis", num_cols, key="cq_cy")
            chart_type = st.radio("Chart type", ["Bar", "Line", "Scatter"], horizontal=True, key="cq_ct")

            plot_df = result[[chart_x, chart_y]].dropna()
            if not plot_df.empty:
                if chart_type == "Bar":
                    fig = px.bar(plot_df, x=chart_x, y=chart_y)
                elif chart_type == "Line":
                    fig = px.line(plot_df, x=chart_x, y=chart_y, markers=True)
                else:
                    fig = px.scatter(plot_df, x=chart_x, y=chart_y)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

    # CSV download
    csv = result.to_csv(index=False).encode()
    st.download_button("⬇️ Download CSV", data=csv, file_name="query_result.csv", mime="text/csv")
