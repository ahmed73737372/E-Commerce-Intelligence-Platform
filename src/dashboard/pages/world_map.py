"""
src/dashboard/pages/world_map.py
=================================

Page 2 — World Map

Interactive choropleth world map colored by economic risk level.

Color rules:
  🟢 Green  = Low Risk
  🟡 Yellow = Medium Risk
  🔴 Red    = High Risk

Hover tooltip: Country Name, Stress Score, Risk Level

Data source: GET /stress-map
"""

import streamlit as st
import pandas as pd

from src.dashboard             import api_client
from src.dashboard.components  import metrics, charts, tables


def render() -> None:
    """Render the World Map page."""

    st.title("🌍 World Economic Stress Map")
    st.caption(
        "Interactive choropleth map showing the latest economic stress classification "
        "for every country in the database. Hover over a country for details."
    )

    # ── Fetch data ─────────────────────────────────────────────────────────────
    with st.spinner("Loading stress map data…"):
        data = api_client.get_stress_map()

    if data is None:
        metrics.render_api_error(
            endpoint="GET /stress-map",
            detail="Could not retrieve stress map data from the API.",
        )
        st.stop()

    if len(data) == 0:
        metrics.render_empty_state(
            "No stress scores found. Run the ETL pipeline first: python main.py"
        )
        st.stop()

    # ── Legend ────────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Countries Shown", len(data))

    df = pd.DataFrame(data)
    if "risk_level" in df.columns:
        col2.metric("🔴 High Risk",   int((df["risk_level"] == "High Risk").sum()))
        col3.metric("🟡 Medium Risk", int((df["risk_level"] == "Medium Risk").sum()))
        col4.metric("🟢 Low Risk",    int((df["risk_level"] == "Low Risk").sum()))

    st.divider()

    # ── Choropleth map ─────────────────────────────────────────────────────────
    charts.render_choropleth_map(data)

    st.divider()

    # ── Data table (collapsible) ───────────────────────────────────────────────
    with st.expander("📋 View Full Data Table", expanded=False):
        st.caption("Showing all countries with their latest stress scores.")

        # Filter controls
        risk_filter = st.multiselect(
            "Filter by Risk Level",
            options=["Low Risk", "Medium Risk", "High Risk"],
            default=["Low Risk", "Medium Risk", "High Risk"],
        )

        filtered = [row for row in data if row.get("risk_level") in risk_filter]
        tables.render_stress_map_table(filtered)
