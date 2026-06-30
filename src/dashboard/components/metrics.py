"""
src/dashboard/components/metrics.py
=====================================

Reusable KPI metric card components.

FUNCTIONS
---------
render_kpi_row(summary)          — 5-column KPI row from /global-summary data
render_country_score_card(data)  — Stress score badge for a single country
render_api_error(endpoint)       — Standardized error message when API fails
render_empty_state(message)      — Empty state for zero-data responses
"""

import streamlit as st

# ── Risk level colors (consistent across all pages) ───────────────────────────
RISK_COLORS = {
    "Low Risk":    "#22c55e",   # green-500
    "Medium Risk": "#eab308",   # yellow-500
    "High Risk":   "#ef4444",   # red-500
}

RISK_EMOJI = {
    "Low Risk":    "🟢",
    "Medium Risk": "🟡",
    "High Risk":   "🔴",
}


def render_kpi_row(summary: dict) -> None:
    """
    Render a 5-column KPI row from /global-summary data.

    Parameters
    ----------
    summary : dict
        Keys: total_countries, average_stress_score,
              high_risk_countries, medium_risk_countries, low_risk_countries
    """
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            label="🌐 Total Countries",
            value=summary.get("total_countries", "—"),
        )
    with col2:
        avg = summary.get("average_stress_score")
        st.metric(
            label="📊 Avg Stress Score",
            value=f"{avg:.1f}" if avg is not None else "—",
            help="Average stress score (0 = stable, 100 = extreme stress)",
        )
    with col3:
        st.metric(
            label="🔴 High Risk",
            value=summary.get("high_risk_countries", "—"),
        )
    with col4:
        st.metric(
            label="🟡 Medium Risk",
            value=summary.get("medium_risk_countries", "—"),
        )
    with col5:
        st.metric(
            label="🟢 Low Risk",
            value=summary.get("low_risk_countries", "—"),
        )


def render_country_score_card(data: dict) -> None:
    """
    Render a styled stress score card for a single country.

    Parameters
    ----------
    data : dict
        Keys: country_name, iso3, latest_year, stress_score, risk_level
    """
    risk_level   = data.get("risk_level")    or "N/A"
    stress_score = data.get("stress_score")
    latest_year  = data.get("latest_year")
    color        = RISK_COLORS.get(risk_level, "#6b7280")
    emoji        = RISK_EMOJI.get(risk_level, "⚪")

    score_display = f"{stress_score:.1f} / 100" if stress_score is not None else "No data"
    year_display  = str(latest_year) if latest_year else "N/A"

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, {color}18 0%, {color}08 100%);
            border-left: 5px solid {color};
            border-radius: 12px;
            padding: 1.5rem 2rem;
            margin: 1rem 0;
        ">
            <h2 style="margin: 0; color: {color};">{emoji} {risk_level}</h2>
            <p style="font-size: 2.5rem; font-weight: 800; margin: 0.5rem 0; color: #1f2937;">
                {score_display}
            </p>
            <p style="color: #6b7280; margin: 0;">Latest data: {year_display}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_api_error(endpoint: str = "", detail: str = "") -> None:
    """
    Display a standardized warning when the API is unreachable or returns no data.

    Parameters
    ----------
    endpoint : str   — The API endpoint that failed (for the message)
    detail   : str   — Additional context
    """
    msg = f"**⚠️ Could not load data from `{endpoint}`**" if endpoint else "**⚠️ Could not load data**"
    st.warning(
        f"{msg}\n\n"
        f"{detail}\n\n"
        "**Make sure the FastAPI server is running:**\n"
        "```\nuvicorn src.api.app:app --reload --port 8000\n```"
    )


def render_empty_state(message: str = "No data available.") -> None:
    """Display a centered empty state message."""
    st.info(f"ℹ️ {message}")
