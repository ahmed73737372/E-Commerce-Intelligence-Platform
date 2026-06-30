"""
src/dashboard/app.py
======================

Phase 7 — Streamlit Dashboard entry point.

RUN
---
From the project root (d:/global):

    streamlit run src/dashboard/app.py

Optional: set API base URL via environment variable:

    $env:API_BASE_URL = "http://localhost:8000"
    streamlit run src/dashboard/app.py

ARCHITECTURE
------------
Uses st.navigation() with grouped st.Page() objects (Streamlit >= 1.36).
Each page is a thin module with a single render() callable.

Navigation Groups:
  Overview   → Home, World Map
  Analysis   → Country Analysis, Rankings, Trends
"""

import sys
from pathlib import Path

# ── Ensure project root is on sys.path so `src.*` imports work ────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from src.dashboard.pages import (
    home,
    world_map,
    country_analysis,
    rankings,
    trends,
)
from src.dashboard import api_client

# ── Page configuration (must be the first Streamlit call) ─────────────────────
st.set_page_config(
    page_title="Global Economic Stress Monitor",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": (
            "**Global Economic Stress Monitoring Platform** — Phase 7\n\n"
            "Data: World Bank · IMF · FRED\n"
            "API: FastAPI (localhost:8000)\n"
            "Built with Streamlit + Plotly"
        ),
    },
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* Import Google Font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }

        /* Sidebar refinements */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        }
        [data-testid="stSidebar"] * {
            color: #e2e8f0 !important;
        }
        [data-testid="stSidebarNavLink"] {
            border-radius: 8px;
            margin: 2px 0;
            transition: background 0.15s;
        }
        [data-testid="stSidebarNavLink"]:hover {
            background: rgba(255,255,255,0.08) !important;
        }
        [data-testid="stSidebarNavLink"][aria-selected="true"] {
            background: rgba(59,130,246,0.25) !important;
            border-left: 3px solid #3b82f6;
        }

        /* Metric cards */
        [data-testid="stMetric"] {
            background: #f8fafc;
            border-radius: 12px;
            padding: 1rem 1.25rem;
            border: 1px solid #e2e8f0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        [data-testid="stMetricLabel"] {
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #64748b !important;
        }
        [data-testid="stMetricValue"] {
            font-weight: 800;
            font-size: 1.8rem;
            color: #0f172a !important;
        }

        /* Divider */
        hr {
            border: none;
            border-top: 1px solid #e2e8f0;
            margin: 1.5rem 0;
        }

        /* Dataframe header */
        [data-testid="stDataFrame"] th {
            background: #f1f5f9 !important;
            font-weight: 700 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── API health check in sidebar ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    status = api_client.get_platform_status()
    if status and status.get("status") == "running":
        st.success("✅ API Connected", icon=None)
    else:
        st.error("❌ API Offline")
        st.caption(
            "Start the server:\n"
            "```\nuvicorn src.api.app:app --port 8000\n```"
        )
    st.caption(f"Endpoint: `{api_client.API_BASE_URL}`")

# ── Navigation ────────────────────────────────────────────────────────────────
pg = st.navigation(
    {
        "🌍 Overview": [
            st.Page(home.render,              title="Home",             icon="🏠", default=True, url_path="home"),
            st.Page(world_map.render,         title="World Map",        icon="🗺️", url_path="world-map"),
        ],
        "📊 Analysis": [
            st.Page(country_analysis.render,  title="Country Analysis", icon="🔍", url_path="country-analysis"),
            st.Page(rankings.render,          title="Rankings",         icon="🏆", url_path="rankings"),
            st.Page(trends.render,            title="Trends",           icon="📈", url_path="trends"),
        ],
    }
)

pg.run()
