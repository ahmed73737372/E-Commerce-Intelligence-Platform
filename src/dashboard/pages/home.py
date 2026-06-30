"""
src/dashboard/pages/home.py
============================

Page 1 — Home

Displays global KPI metrics and risk distribution.

Data source: GET /global-summary
"""

import streamlit as st

from src.dashboard              import api_client
from src.dashboard.components  import metrics, charts


def render() -> None:
    """Render the Home page."""

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
            border-radius: 16px;
            padding: 2.5rem 3rem;
            margin-bottom: 2rem;
            color: white;
        ">
            <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800;">
                🌐 Global Economic Stress Monitor
            </h1>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.85; font-size: 1.05rem;">
                Real-time economic risk intelligence powered by World Bank, IMF, and FRED data.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Fetch data ─────────────────────────────────────────────────────────────
    with st.spinner("Loading global summary…"):
        summary = api_client.get_global_summary()

    if summary is None:
        metrics.render_api_error(
            endpoint="GET /global-summary",
            detail="The API returned no data. The database may be empty — run the ETL pipeline first.",
        )
        st.stop()

    # ── KPI cards ─────────────────────────────────────────────────────────────
    st.markdown("### 📊 Current Global Overview")
    metrics.render_kpi_row(summary)

    st.divider()

    # ── Risk distribution chart + summary text ────────────────────────────────
    col_chart, col_text = st.columns([1, 1], gap="large")

    with col_chart:
        charts.render_risk_pie_chart(summary)

    with col_text:
        st.markdown("### 🗺️ Risk Breakdown")
        total = summary.get("total_countries", 0)
        high  = summary.get("high_risk_countries",   0)
        med   = summary.get("medium_risk_countries",  0)
        low   = summary.get("low_risk_countries",    0)

        if total > 0:
            st.markdown(
                f"""
                | Risk Level | Countries | Share |
                |:-----------|:---------:|------:|
                | 🔴 High Risk | **{high}** | {high/total*100:.0f}% |
                | 🟡 Medium Risk | **{med}** | {med/total*100:.0f}% |
                | 🟢 Low Risk | **{low}** | {low/total*100:.0f}% |
                | **Total** | **{total}** | 100% |
                """
            )

        avg = summary.get("average_stress_score", 0)
        if avg is not None:
            if avg >= 61:
                overall_label = "🔴 High Global Stress"
                note = "The global economy is showing significant stress indicators."
            elif avg >= 31:
                overall_label = "🟡 Moderate Global Stress"
                note = "The global economy shows moderate stress across multiple regions."
            else:
                overall_label = "🟢 Low Global Stress"
                note = "The global economy is relatively stable."

            st.markdown(f"**Overall Assessment:** {overall_label}")
            st.caption(note)

    st.divider()

    # ── How it works ──────────────────────────────────────────────────────────
    st.markdown("### ℹ️ How Stress Scores Are Calculated")
    st.markdown(
        """
        The Economic Stress Score (0–100) is a weighted composite of 5 indicators:

        | Indicator | Weight | Direction |
        |:----------|:------:|----------:|
        | Inflation Rate | 35% | Higher = More stress |
        | Unemployment Rate | 25% | Higher = More stress |
        | Government Debt (% GDP) | 20% | Higher = More stress |
        | Interest Rate | 15% | Higher = More stress |
        | GDP Growth | 15% | Higher = **Less** stress |

        Scores are min-max normalised across all countries in the dataset.
        """
    )
