"""
src/dashboard/api_client.py
============================

Centralized API client for the Streamlit dashboard (Phase 7).

RULES
-----
- ALL HTTP requests to the FastAPI backend go through this module
- Page files must NEVER import `requests` directly
- Functions return Python dicts/lists on success, None on any failure
- Failures are logged via st.warning() at call site, not here
- Responses are cached with @st.cache_data to avoid re-hitting the API
  on every Streamlit widget interaction

CONFIGURATION
-------------
API_BASE_URL defaults to http://localhost:8000
Override by setting the API_BASE_URL environment variable:

    $env:API_BASE_URL = "http://myserver:8000"
    streamlit run src/dashboard/app.py

ERROR HANDLING
--------------
Every function catches:
  - ConnectionError   — API server is not running
  - Timeout           — API is slow / overloaded
  - HTTPError         — API returned 4xx / 5xx
  - JSONDecodeError   — response is not valid JSON
  - Exception         — any other unexpected error

All errors return None. The caller shows a friendly st.warning().
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger("platform.dashboard.api_client")

# ── Configuration ─────────────────────────────────────────────────────────────
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT: int     = 10   # seconds per request


# ── Private helper ─────────────────────────────────────────────────────────────

def _get(endpoint: str) -> Optional[dict | list]:
    """
    Internal GET request with full error handling.

    Parameters
    ----------
    endpoint : str  — path relative to API_BASE_URL, e.g. "/countries"

    Returns
    -------
    dict | list | None
        Parsed JSON on success, None on any failure.
    """
    url = f"{API_BASE_URL}{endpoint}"
    try:
        response = requests.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        logger.warning("API unavailable: could not connect to %s", url)
        return None
    except requests.exceptions.Timeout:
        logger.warning("API timeout after %ds: %s", _TIMEOUT, url)
        return None
    except requests.exceptions.HTTPError as exc:
        logger.warning("API HTTP error %s: %s", exc.response.status_code, url)
        return None
    except (ValueError, requests.exceptions.JSONDecodeError):
        logger.warning("API returned invalid JSON: %s", url)
        return None
    except Exception as exc:
        logger.warning("Unexpected API error at %s: %s", url, exc)
        return None


# ── Public API functions ───────────────────────────────────────────────────────

def get_platform_status() -> Optional[dict]:
    """GET / — Health check."""
    return _get("/")


def get_global_summary() -> Optional[dict]:
    """
    GET /global-summary

    Returns
    -------
    dict with keys:
        total_countries, average_stress_score,
        high_risk_countries, medium_risk_countries, low_risk_countries
    """
    return _get("/global-summary")


def get_countries() -> Optional[list]:
    """
    GET /countries

    Returns
    -------
    list of {"iso3": str, "name": str}
    """
    return _get("/countries")


def get_country_detail(iso3: str) -> Optional[dict]:
    """
    GET /country/{iso3}

    Returns
    -------
    dict with keys:
        iso3, country_name, latest_year, stress_score, risk_level, indicators
    """
    if not iso3:
        return None
    return _get(f"/country/{iso3.upper()}")


def get_top_risk(limit: int = 10) -> Optional[list]:
    """
    GET /top-risk?limit={limit}

    Returns
    -------
    list of {iso3, country_name, year, stress_score, risk_level}
    ordered by stress_score DESC
    """
    return _get(f"/top-risk?limit={limit}")


def get_top_safe(limit: int = 10) -> Optional[list]:
    """
    GET /top-safe?limit={limit}

    Returns
    -------
    list of {iso3, country_name, year, stress_score, risk_level}
    ordered by stress_score ASC
    """
    return _get(f"/top-safe?limit={limit}")


def get_stress_map() -> Optional[list]:
    """
    GET /stress-map

    Returns
    -------
    list of {iso3, country_name, year, stress_score, risk_level}
    for all scored countries — used for the choropleth map.
    """
    return _get("/stress-map")


def get_country_history(iso3: str) -> Optional[list]:
    """
    GET /country/{iso3}/history

    Returns
    -------
    list of {year, stress_score, risk_level, raw_score} ordered by year ASC.
    Used by the Trends page per-country line chart.
    """
    if not iso3:
        return None
    return _get(f"/country/{iso3.upper()}/history")


def get_global_trend() -> Optional[list]:
    """
    GET /global-trend

    Returns
    -------
    list of {year, avg_stress_score, country_count} ordered by year ASC.
    Used by the Trends page global average chart.
    """
    return _get("/global-trend")


def get_indicator_trend(code: str, iso3_list: Optional[list] = None) -> Optional[list]:
    """
    GET /indicator-trend/{code}?iso3=USA,DEU,...

    Returns
    -------
    list of {year, avg_value, country_count} ordered by year ASC.
    Used by the Trends page indicator deep-dive chart.
    """
    if not code:
        return None
    endpoint = f"/indicator-trend/{code.upper()}"
    if iso3_list:
        endpoint += f"?iso3={','.join(iso3_list)}"
    return _get(endpoint)
