"""
src/dashboard/pages/rankings.py
=================================

Page 4 — Rankings

Displays Top 10 highest-risk and Top 10 safest countries
as both bar charts and sortable tables.

Data sources:
  GET /top-risk   — highest stress scores
  GET /top-safe   — lowest stress scores
"""

import streamlit as st

from src.dashboard             import api_client
from src.dashboard.components  import metrics, charts, tables


def render() -> None:
    """Render the Rankings page."""

    st.title("🏆 Country Risk Rankings")
    st.caption(
        "Comparing the most economically stressed and most stable countries "
        "based on the latest available stress scores."
    )

    # ── Fetch both ranking lists ───────────────────────────────────────────────
    with st.spinner("Loading rankings…"):
        top_risk = api_client.get_top_risk(limit=10)
        top_safe = api_client.get_top_safe(limit=10)

    # ── Handle API errors ──────────────────────────────────────────────────────
    if top_risk is None and top_safe is None:
        metrics.render_api_error(
            endpoint="GET /top-risk, GET /top-safe",
            detail="Could not load ranking data from the API.",
        )
        st.stop()

    # ── Side-by-side layout ────────────────────────────────────────────────────
    col_risk, col_safe = st.columns(2, gap="large")

    # ── Top 10 Highest Risk ────────────────────────────────────────────────────
    with col_risk:
        st.markdown(
            """
            <div style="
                background: linear-gradient(135deg, #fee2e2 0%, #fff7ed 100%);
                border-left: 5px solid #ef4444;
                border-radius: 12px;
                padding: 1rem 1.5rem;
                margin-bottom: 1rem;
            ">
                <h3 style="margin: 0; color: #991b1b;">🔴 Most Stressed Economies</h3>
                <p style="margin: 0.25rem 0 0 0; color: #6b7280; font-size: 0.9rem;">
                    Highest economic stress score (worst → best)
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if top_risk:
            charts.render_rankings_bar_chart(
                top_risk,
                title="Top 10 Highest Risk Countries",
                ascending=False,
            )
            st.divider()
            tables.render_rankings_table(top_risk)
        else:
            metrics.render_empty_state("No high-risk data available.")

    # ── Top 10 Safest ──────────────────────────────────────────────────────────
    with col_safe:
        st.markdown(
            """
            <div style="
                background: linear-gradient(135deg, #dcfce7 0%, #f0fdf4 100%);
                border-left: 5px solid #22c55e;
                border-radius: 12px;
                padding: 1rem 1.5rem;
                margin-bottom: 1rem;
            ">
                <h3 style="margin: 0; color: #166534;">🟢 Most Stable Economies</h3>
                <p style="margin: 0.25rem 0 0 0; color: #6b7280; font-size: 0.9rem;">
                    Lowest economic stress score (best → worst)
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if top_safe:
            charts.render_rankings_bar_chart(
                top_safe,
                title="Top 10 Lowest Risk Countries",
                ascending=True,
            )
            st.divider()
            tables.render_rankings_table(top_safe)
        else:
            metrics.render_empty_state("No safe-country data available.")

    st.divider()

    # ── Methodology note ──────────────────────────────────────────────────────
    with st.expander("ℹ️ About This Ranking"):
        st.markdown(
            """
            Rankings are based on the **latest available stress score** for each country.
            Different countries may have data from different years depending on API availability.

            **Stress Score Formula:**
            ```
            raw = 0.35×Inflation + 0.25×Unemployment + 0.20×GovtDebt
                + 0.15×InterestRate − 0.15×GDPGrowth

            stress_score = (raw − min) / (max − min) × 100
            ```
            Scores range from **0** (no stress) to **100** (maximum stress).
            """
        )
