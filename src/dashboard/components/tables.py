"""
src/dashboard/components/tables.py
=====================================

Reusable styled table components for the dashboard.

FUNCTIONS
---------
render_rankings_table(data, title)   — Styled table for top-risk / top-safe
render_indicators_table(indicators)  — Economic indicators for a country
render_stress_map_table(data)        — Full country list with stress scores
"""

import streamlit as st
import pandas as pd


# ── Risk badge HTML ────────────────────────────────────────────────────────────
_RISK_BADGE = {
    "Low Risk":    '<span style="background:#dcfce7;color:#166534;padding:2px 10px;border-radius:20px;font-size:0.8rem;font-weight:600;">🟢 Low Risk</span>',
    "Medium Risk": '<span style="background:#fef9c3;color:#854d0e;padding:2px 10px;border-radius:20px;font-size:0.8rem;font-weight:600;">🟡 Medium Risk</span>',
    "High Risk":   '<span style="background:#fee2e2;color:#991b1b;padding:2px 10px;border-radius:20px;font-size:0.8rem;font-weight:600;">🔴 High Risk</span>',
}


def _badge(risk_level: str) -> str:
    return _RISK_BADGE.get(risk_level, risk_level)


def render_rankings_table(data: list, title: str = "") -> None:
    """
    Render a styled rankings table (top-risk or top-safe).

    Parameters
    ----------
    data  : list of dicts — Keys: country_name, iso3, stress_score, risk_level, year
    title : str           — Optional section header
    """
    if not data:
        st.info("ℹ️ No ranking data available.")
        return

    if title:
        st.markdown(f"#### {title}")

    df = pd.DataFrame(data)

    # Rename and select display columns
    display = df[["country_name", "iso3", "stress_score", "risk_level"]].copy()
    display.columns = ["Country", "ISO3", "Stress Score", "Risk Level"]
    display["Rank"] = range(1, len(display) + 1)
    display = display[["Rank", "Country", "ISO3", "Stress Score", "Risk Level"]]
    display["Stress Score"] = display["Stress Score"].round(1)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank":        st.column_config.NumberColumn("Rank",         width="small"),
            "Country":     st.column_config.TextColumn("Country",        width="medium"),
            "ISO3":        st.column_config.TextColumn("ISO3",           width="small"),
            "Stress Score":st.column_config.NumberColumn("Stress Score", width="small",  format="%.1f"),
            "Risk Level":  st.column_config.TextColumn("Risk Level",     width="medium"),
        },
    )


def render_indicators_table(indicators: list) -> None:
    """
    Render an economic indicators table for a single country.

    Parameters
    ----------
    indicators : list of dicts — Keys: code, label, year, value
    """
    if not indicators:
        st.info("ℹ️ No indicator data available for this country.")
        return

    df = pd.DataFrame(indicators)

    display = df[["label", "code", "year", "value"]].copy()
    display.columns = ["Indicator", "Code", "Year", "Value"]
    display["Value"] = display["Value"].round(3)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Indicator": st.column_config.TextColumn("Indicator",   width="large"),
            "Code":      st.column_config.TextColumn("Code",        width="medium"),
            "Year":      st.column_config.NumberColumn("Year",      width="small",  format="%d"),
            "Value":     st.column_config.NumberColumn("Value",     width="small",  format="%.3f"),
        },
    )


def render_stress_map_table(data: list) -> None:
    """
    Render a searchable table of all countries and their stress scores.

    Parameters
    ----------
    data : list of dicts — Keys: iso3, country_name, stress_score, risk_level, year
    """
    if not data:
        st.info("ℹ️ No stress score data available.")
        return

    df = pd.DataFrame(data)

    display = df[["country_name", "iso3", "stress_score", "risk_level"]].copy()
    display.columns = ["Country", "ISO3", "Stress Score", "Risk Level"]
    display["Stress Score"] = display["Stress Score"].round(1)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Country":     st.column_config.TextColumn("Country",        width="medium"),
            "ISO3":        st.column_config.TextColumn("ISO3",           width="small"),
            "Stress Score":st.column_config.ProgressColumn(
                "Stress Score",
                min_value=0,
                max_value=100,
                format="%.1f",
                width="large",
            ),
            "Risk Level":  st.column_config.TextColumn("Risk Level",     width="medium"),
        },
    )
