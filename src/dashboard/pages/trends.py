"""
src/dashboard/pages/trends.py
================================

Page 5 - Historical Trends

Displays real historical stress score data from the FastAPI backend:
  - Per-country stress score line chart  (GET /country/{iso3}/history)
  - Global average stress score over time (GET /global-trend)
  - Indicator deep-dive chart             (GET /indicator-trend/{code})
"""

import pandas as pd
import streamlit as st

from src.dashboard            import api_client
from src.dashboard.components import metrics, charts

_INDICATOR_LABELS = {
    "GDP_GROWTH_PCT":          "Real GDP Growth (%)",
    "INFLATION_PCT":           "Inflation Rate (%)",
    "UNEMPLOYMENT_PCT":        "Unemployment Rate (%)",
    "INTEREST_RATE_PCT":       "Interest Rate (%)",
    "GOVT_DEBT_PCT_GDP":       "Government Debt (% of GDP)",
    "CURRENT_ACCOUNT_PCT_GDP": "Current Account Balance (% of GDP)",
}


def render() -> None:
    """Render the Trends page with real historical data."""

    st.title("Historical Trends")
    st.caption(
        "Time-series analysis of economic stress scores and macroeconomic indicators "
        "from 2000 to 2024, sourced directly from the platform database."
    )

    # -- Section 1: Country stress score over time ----------------------------
    st.markdown("---")
    st.markdown("### Country Stress Score Over Time")

    with st.spinner("Loading countries..."):
        countries = api_client.get_countries()

    if not countries:
        metrics.render_api_error(
            endpoint="GET /countries",
            detail="Could not load country list.",
        )
    else:
        country_map = {c["name"]: c["iso3"] for c in countries if c.get("name")}
        selected_name = st.selectbox(
            "Select Country",
            options=["--- Choose a country ---"] + sorted(country_map.keys()),
            key="trend_country_select",
        )

        if selected_name != "--- Choose a country ---":
            selected_iso3 = country_map[selected_name]

            with st.spinner("Loading history..."):
                history = api_client.get_country_history(selected_iso3)

            if history:
                charts.render_country_trend_chart(history, selected_name)
                scores = [r["stress_score"] for r in history]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Years of Data", len(scores))
                c2.metric("Latest Score",  f"{scores[-1]:.1f}")
                c3.metric("Peak Score",    f"{max(scores):.1f}")
                c4.metric("Lowest Score",  f"{min(scores):.1f}")
            else:
                st.info("No historical data found for this country.")

    # -- Section 2: Global average trend --------------------------------------
    st.markdown("---")
    st.markdown("### Global Average Stress Over Time")
    st.caption("Average economic stress score across all scored countries, per year.")

    with st.spinner("Loading global trend..."):
        global_trend = api_client.get_global_trend()

    if global_trend:
        charts.render_global_trend_chart(global_trend)
        with st.expander("View Global Trend Data"):
            df = pd.DataFrame(global_trend)
            df.columns = ["Year", "Avg Stress Score", "Countries Scored"]
            st.dataframe(df.set_index("Year"), use_container_width=True)
    else:
        metrics.render_api_error(
            endpoint="GET /global-trend",
            detail="Could not load global trend data.",
        )

    # -- Section 3: Indicator deep-dive ---------------------------------------
    st.markdown("---")
    st.markdown("### Indicator Deep-Dive")
    st.caption("Global average value of a single economic indicator per year.")

    label_to_code = {label: code for code, label in _INDICATOR_LABELS.items()}
    selected_label = st.selectbox(
        "Select Indicator",
        options=["--- Choose an indicator ---"] + list(_INDICATOR_LABELS.values()),
        key="trend_indicator_select",
    )

    if selected_label != "--- Choose an indicator ---":
        selected_code = label_to_code[selected_label]
        with st.spinner("Loading trend..."):
            ind_trend = api_client.get_indicator_trend(selected_code)
        if ind_trend:
            charts.render_indicator_trend_chart(ind_trend, selected_label)
        else:
            st.info("No data available for this indicator.")
