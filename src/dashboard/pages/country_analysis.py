"""
src/dashboard/pages/country_analysis.py
=========================================

Page 3 — Country Analysis

Select a country from a dropdown and view:
  - Country profile (name, ISO3, latest year, risk level)
  - Stress score card
  - Economic indicators table

Data sources:
  GET /countries          — populate the dropdown
  GET /country/{iso3}     — load selected country detail
"""

import streamlit as st

from src.dashboard             import api_client
from src.dashboard.components  import metrics, tables


def render() -> None:
    """Render the Country Analysis page."""

    st.title("📊 Country Analysis")
    st.caption(
        "Select a country to view its latest economic stress score "
        "and all available economic indicators."
    )

    # ── Fetch country list for dropdown ───────────────────────────────────────
    with st.spinner("Loading country list…"):
        countries = api_client.get_countries()

    if countries is None:
        metrics.render_api_error(
            endpoint="GET /countries",
            detail="Could not load the country list from the API.",
        )
        st.stop()

    if not countries:
        metrics.render_empty_state("No countries found in the database.")
        st.stop()

    # ── Country dropdown ──────────────────────────────────────────────────────
    country_map = {c["name"]: c["iso3"] for c in countries}
    country_names = sorted(country_map.keys())

    selected_name = st.selectbox(
        "Select a Country",
        options=["— Choose a country —"] + country_names,
        index=0,
    )

    if selected_name == "— Choose a country —":
        st.info("👆 Select a country from the dropdown above to view its economic profile.")
        return

    selected_iso3 = country_map[selected_name]

    # ── Fetch country detail ───────────────────────────────────────────────────
    with st.spinner(f"Loading data for {selected_name}…"):
        detail = api_client.get_country_detail(selected_iso3)

    if detail is None:
        metrics.render_api_error(
            endpoint=f"GET /country/{selected_iso3}",
            detail=f"Could not load details for {selected_name}.",
        )
        return

    # ── Country header ─────────────────────────────────────────────────────────
    st.divider()
    col_info, col_score = st.columns([1.2, 1], gap="large")

    with col_info:
        st.markdown(f"## {detail.get('country_name', selected_name)}")
        st.markdown(f"**ISO3 Code:** `{detail.get('iso3', selected_iso3)}`")

        latest_year = detail.get("latest_year")
        if latest_year:
            st.markdown(f"**Latest Data Year:** {latest_year}")
        else:
            st.markdown("**Latest Data Year:** N/A")

        risk = detail.get("risk_level")
        if risk:
            risk_emoji = {"Low Risk": "🟢", "Medium Risk": "🟡", "High Risk": "🔴"}.get(risk, "⚪")
            st.markdown(f"**Risk Classification:** {risk_emoji} {risk}")
        else:
            st.markdown("**Risk Classification:** No stress score calculated yet.")

    with col_score:
        metrics.render_country_score_card(detail)

    st.divider()

    # ── Economic indicators table ─────────────────────────────────────────────
    st.markdown("### 📈 Economic Indicators (Latest Available Year)")

    indicators = detail.get("indicators", [])
    if not indicators:
        st.info(
            "ℹ️ No indicator data found for this country. "
            "The ETL pipeline may not have collected data for this region yet."
        )
    else:
        st.caption(
            f"Showing {len(indicators)} indicator(s). "
            "Each value is the most recent year available in the database."
        )
        tables.render_indicators_table(indicators)

    # ── Missing stress score note ─────────────────────────────────────────────
    if detail.get("stress_score") is None:
        st.warning(
            "⚠️ No stress score has been calculated for this country. "
            "This usually means one or more of the 5 required indicators "
            "(GDP Growth, Inflation, Unemployment, Interest Rate, Govt Debt) "
            "are missing from the database."
        )
