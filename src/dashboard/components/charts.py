"""
src/dashboard/components/charts.py
=====================================

Reusable Plotly chart components for the dashboard.

FUNCTIONS
---------
render_choropleth_map(data)              — World choropleth by risk level
render_risk_pie_chart(summary)           — Risk distribution donut chart
render_rankings_bar_chart(data, title)   — Horizontal bar chart for top/safe lists
render_placeholder_trend_chart(title)    — Placeholder line chart for Trends page
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# ── Consistent color palette ──────────────────────────────────────────────────
RISK_COLOR_MAP = {
    "Low Risk":    "#22c55e",
    "Medium Risk": "#eab308",
    "High Risk":   "#ef4444",
}

_CHART_BG    = "rgba(0,0,0,0)"   # transparent — adapts to Streamlit theme
_FONT_COLOR  = "#374151"         # neutral-700


def render_choropleth_map(data: list) -> None:
    """
    Render an interactive world choropleth map colored by risk level.

    Parameters
    ----------
    data : list of dicts
        Keys: iso3, country_name, stress_score, risk_level
    """
    if not data:
        st.info("ℹ️ No stress score data available. Run the ETL pipeline first.")
        return

    df = pd.DataFrame(data)

    # Ensure risk_level column is ordered for consistent legend order
    risk_order = ["Low Risk", "Medium Risk", "High Risk"]
    df["risk_level"] = pd.Categorical(df["risk_level"], categories=risk_order, ordered=True)
    df = df.sort_values("risk_level")

    fig = px.choropleth(
        df,
        locations="iso3",
        color="risk_level",
        color_discrete_map=RISK_COLOR_MAP,
        hover_name="country_name",
        hover_data={
            "iso3":         False,
            "stress_score": ":.1f",
            "risk_level":   True,
        },
        labels={
            "stress_score": "Stress Score",
            "risk_level":   "Risk Level",
        },
        title="Global Economic Stress — Latest Year",
        category_orders={"risk_level": risk_order},
    )

    fig.update_layout(
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        geo=dict(
            showframe=False,
            showcoastlines=True,
            coastlinecolor="#d1d5db",
            showland=True,
            landcolor="#f9fafb",
            showocean=True,
            oceancolor="#eff6ff",
            showlakes=False,
            projection_type="natural earth",
        ),
        legend=dict(
            title="Risk Level",
            orientation="v",
            x=0.01,
            y=0.5,
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        height=520,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_risk_pie_chart(summary: dict) -> None:
    """
    Render a donut chart of risk distribution from /global-summary data.

    Parameters
    ----------
    summary : dict
        Keys: high_risk_countries, medium_risk_countries, low_risk_countries
    """
    labels = ["Low Risk", "Medium Risk", "High Risk"]
    values = [
        summary.get("low_risk_countries",    0),
        summary.get("medium_risk_countries", 0),
        summary.get("high_risk_countries",   0),
    ]
    colors = [RISK_COLOR_MAP[l] for l in labels]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        marker_colors=colors,
        hole=0.55,
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>%{value} countries<extra></extra>",
    ))

    fig.update_layout(
        title="Risk Distribution",
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        showlegend=False,
        margin=dict(l=20, r=20, t=50, b=20),
        height=320,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_rankings_bar_chart(data: list, title: str, ascending: bool = False) -> None:
    """
    Render a horizontal bar chart for top-risk or top-safe rankings.

    Parameters
    ----------
    data       : list of dicts — Keys: country_name, stress_score, risk_level
    title      : str           — Chart title
    ascending  : bool          — True = low scores first (safe), False = high first (risk)
    """
    if not data:
        st.info("ℹ️ No ranking data available.")
        return

    df = pd.DataFrame(data)
    df = df.sort_values("stress_score", ascending=ascending)
    df["color"] = df["risk_level"].map(RISK_COLOR_MAP).fillna("#6b7280")

    fig = go.Figure(go.Bar(
        x=df["stress_score"],
        y=df["country_name"],
        orientation="h",
        marker_color=df["color"].tolist(),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Stress Score: %{x:.1f}<br>"
            "<extra></extra>"
        ),
        text=df["stress_score"].round(1),
        textposition="outside",
    ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="Stress Score (0–100)", range=[0, 105]),
        yaxis=dict(title=""),
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        font=dict(color=_FONT_COLOR),
        margin=dict(l=10, r=60, t=50, b=30),
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_placeholder_trend_chart(title: str = "Historical Trend") -> None:
    """
    Render a placeholder trend line chart with a clear TODO message.
    Kept for backward compatibility — the Trends page now uses real chart functions.
    """
    st.markdown(
        f"""
        <div style="
            border: 2px dashed #d1d5db;
            border-radius: 12px;
            padding: 3rem;
            text-align: center;
            background: #f9fafb;
            margin: 1rem 0;
        ">
            <h3 style="color: #6b7280; margin-bottom: 0.5rem;">📈 {title}</h3>
            <p style="color: #9ca3af; margin: 0;">
                <strong>TODO:</strong> Add a historical data endpoint to Phase 6 API<br>
                <code>GET /country/{{iso3}}/history?years=10</code><br><br>
                Then replace this placeholder with a Plotly line chart using<br>
                <code>render_trend_chart(data, iso3)</code>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_country_trend_chart(data: list, country_name: str) -> None:
    """
    Render a line chart of historical stress scores for one country.

    Parameters
    ----------
    data         : list of {year, stress_score, risk_level}
    country_name : str — used as chart title
    """
    if not data:
        st.info("No historical data available for this country.")
        return

    df = pd.DataFrame(data)
    df = df.sort_values("year")

    fig = px.line(
        df,
        x="year",
        y="stress_score",
        title=f"{country_name} — Stress Score History",
        markers=True,
        labels={"year": "Year", "stress_score": "Stress Score (0–100)"},
    )
    fig.update_traces(
        line=dict(color="#3b82f6", width=2.5),
        marker=dict(size=7, color="#1d4ed8"),
    )
    # Add risk-level coloured background bands
    fig.add_hrect(y0=0,  y1=30,  fillcolor="#22c55e", opacity=0.07, line_width=0, annotation_text="Low Risk",    annotation_position="right")
    fig.add_hrect(y0=30, y1=60,  fillcolor="#eab308", opacity=0.07, line_width=0, annotation_text="Medium Risk", annotation_position="right")
    fig.add_hrect(y0=60, y1=100, fillcolor="#ef4444", opacity=0.07, line_width=0, annotation_text="High Risk",   annotation_position="right")
    fig.update_layout(
        yaxis=dict(range=[0, 105], title="Stress Score"),
        xaxis=dict(title="Year", dtick=2),
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        font=dict(color=_FONT_COLOR),
        margin=dict(l=10, r=80, t=50, b=30),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_global_trend_chart(data: list) -> None:
    """
    Render the global average stress score per year as a line chart.

    Parameters
    ----------
    data : list of {year, avg_stress_score, country_count}
    """
    if not data:
        st.info("No global trend data available.")
        return

    df = pd.DataFrame(data)
    df = df.sort_values("year")

    fig = px.line(
        df,
        x="year",
        y="avg_stress_score",
        title="Global Average Stress Score — All Countries (2000–2024)",
        markers=True,
        labels={"year": "Year", "avg_stress_score": "Avg Stress Score"},
        custom_data=["country_count"],
    )
    fig.update_traces(
        line=dict(color="#8b5cf6", width=2.5),
        marker=dict(size=7, color="#6d28d9"),
        hovertemplate="Year: %{x}<br>Avg Score: %{y:.2f}<br>Countries: %{customdata[0]}<extra></extra>",
    )
    fig.update_layout(
        yaxis=dict(range=[0, 105]),
        xaxis=dict(dtick=2),
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        font=dict(color=_FONT_COLOR),
        margin=dict(l=10, r=20, t=50, b=30),
        height=380,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_indicator_trend_chart(data: list, indicator_label: str) -> None:
    """
    Render a global average trend line for a single economic indicator.

    Parameters
    ----------
    data             : list of {year, avg_value, country_count}
    indicator_label  : str — human readable name shown in the title
    """
    if not data:
        st.info(f"No trend data available for {indicator_label}.")
        return

    df = pd.DataFrame(data)
    df = df.sort_values("year")

    fig = px.line(
        df,
        x="year",
        y="avg_value",
        title=f"Global Average — {indicator_label} (2000–2024)",
        markers=True,
        labels={"year": "Year", "avg_value": indicator_label},
    )
    fig.update_traces(line=dict(color="#f59e0b", width=2.5), marker=dict(size=7))
    fig.update_layout(
        xaxis=dict(dtick=2),
        paper_bgcolor=_CHART_BG,
        plot_bgcolor=_CHART_BG,
        font=dict(color=_FONT_COLOR),
        margin=dict(l=10, r=20, t=50, b=30),
        height=360,
    )
    st.plotly_chart(fig, use_container_width=True)
