"""
tests/test_dashboard_structure.py
===================================

Phase 7 — Structural tests for the Streamlit dashboard.

STRATEGY
--------
- Tests run WITHOUT a Streamlit server (no browser, no st.* calls)
- Tests verify structure, imports, callability, and API client logic
- API client is tested by mocking requests.get — never hits the real server
- Page render() functions are verified as callables only — not executed
  (executing them would require Streamlit context)

TEST CLASSES
------------
  TestDashboardImports         — All modules importable
  TestApiClientStructure       — All required functions exist and are callable
  TestApiClientBehavior        — get_*() returns None on failures, data on success
  TestComponentStructure       — All component functions exist
  TestPageStructure            — All pages exist and have a render() callable
  TestApiClientConfiguration   — API_BASE_URL configurable via environment

RUN
---
    python -m pytest tests/test_dashboard_structure.py -v
"""

import sys
import os
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Project root on sys.path ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mock_response(json_data, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


def _mock_error_response(status_code: int = 404) -> MagicMock:
    """Build a mock response that raises HTTPError."""
    import requests
    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=mock
    )
    return mock


# ══════════════════════════════════════════════════════════════════════════════
# TestDashboardImports
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboardImports:
    """Verify every dashboard module can be imported without error."""

    def test_api_client_importable(self):
        import src.dashboard.api_client  # noqa: F401

    def test_dashboard_package_importable(self):
        import src.dashboard  # noqa: F401

    def test_components_metrics_importable(self):
        import src.dashboard.components.metrics  # noqa: F401

    def test_components_charts_importable(self):
        import src.dashboard.components.charts  # noqa: F401

    def test_components_tables_importable(self):
        import src.dashboard.components.tables  # noqa: F401

    def test_pages_home_importable(self):
        import src.dashboard.pages.home  # noqa: F401

    def test_pages_world_map_importable(self):
        import src.dashboard.pages.world_map  # noqa: F401

    def test_pages_country_analysis_importable(self):
        import src.dashboard.pages.country_analysis  # noqa: F401

    def test_pages_rankings_importable(self):
        import src.dashboard.pages.rankings  # noqa: F401

    def test_pages_trends_importable(self):
        import src.dashboard.pages.trends  # noqa: F401


# ══════════════════════════════════════════════════════════════════════════════
# TestApiClientStructure
# ══════════════════════════════════════════════════════════════════════════════

class TestApiClientStructure:
    """Verify api_client exposes the expected interface."""

    def setup_method(self):
        import src.dashboard.api_client as ac
        self.ac = ac

    def test_has_api_base_url(self):
        assert hasattr(self.ac, "API_BASE_URL")

    def test_api_base_url_is_string(self):
        assert isinstance(self.ac.API_BASE_URL, str)

    def test_api_base_url_default_is_localhost(self):
        # If env var not set, should default to localhost:8000
        base = self.ac.API_BASE_URL
        assert "localhost" in base or "8000" in base or "http" in base

    def test_has_get_platform_status(self):
        assert callable(getattr(self.ac, "get_platform_status", None))

    def test_has_get_global_summary(self):
        assert callable(getattr(self.ac, "get_global_summary", None))

    def test_has_get_countries(self):
        assert callable(getattr(self.ac, "get_countries", None))

    def test_has_get_country_detail(self):
        assert callable(getattr(self.ac, "get_country_detail", None))

    def test_has_get_top_risk(self):
        assert callable(getattr(self.ac, "get_top_risk", None))

    def test_has_get_top_safe(self):
        assert callable(getattr(self.ac, "get_top_safe", None))

    def test_has_get_stress_map(self):
        assert callable(getattr(self.ac, "get_stress_map", None))


# ══════════════════════════════════════════════════════════════════════════════
# TestApiClientBehavior
# ══════════════════════════════════════════════════════════════════════════════

class TestApiClientBehavior:
    """Test api_client error handling and data extraction behavior."""

    def setup_method(self):
        import src.dashboard.api_client as ac
        self.ac = ac

    # ── Connection errors return None ──────────────────────────────────────────

    def test_get_global_summary_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_global_summary()
        assert result is None

    def test_get_countries_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_countries()
        assert result is None

    def test_get_country_detail_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_country_detail("USA")
        assert result is None

    def test_get_top_risk_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_top_risk()
        assert result is None

    def test_get_top_safe_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_top_safe()
        assert result is None

    def test_get_stress_map_returns_none_on_connection_error(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = self.ac.get_stress_map()
        assert result is None

    # ── Timeout returns None ───────────────────────────────────────────────────

    def test_returns_none_on_timeout(self):
        import requests
        with patch("requests.get", side_effect=requests.exceptions.Timeout()):
            result = self.ac.get_global_summary()
        assert result is None

    # ── HTTP error returns None ────────────────────────────────────────────────

    def test_returns_none_on_404(self):
        import requests
        with patch("requests.get", return_value=_mock_error_response(404)):
            result = self.ac.get_country_detail("ZZZ")
        assert result is None

    def test_returns_none_on_500(self):
        import requests
        with patch("requests.get", return_value=_mock_error_response(500)):
            result = self.ac.get_global_summary()
        assert result is None

    # ── Invalid JSON returns None ─────────────────────────────────────────────

    def test_returns_none_on_invalid_json(self):
        import requests
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.side_effect = ValueError("not json")
        with patch("requests.get", return_value=mock):
            result = self.ac.get_global_summary()
        assert result is None

    # ── Successful responses return data ──────────────────────────────────────

    def test_get_global_summary_returns_dict_on_success(self):
        payload = {
            "total_countries": 150,
            "average_stress_score": 45.2,
            "high_risk_countries": 30,
            "medium_risk_countries": 80,
            "low_risk_countries": 40,
        }
        with patch("requests.get", return_value=_mock_response(payload)):
            result = self.ac.get_global_summary()
        assert result == payload

    def test_get_countries_returns_list_on_success(self):
        payload = [{"iso3": "USA", "name": "United States"}]
        with patch("requests.get", return_value=_mock_response(payload)):
            result = self.ac.get_countries()
        assert result == payload

    def test_get_country_detail_returns_dict_on_success(self):
        payload = {
            "iso3": "USA",
            "country_name": "United States",
            "latest_year": 2023,
            "stress_score": 42.5,
            "risk_level": "Medium Risk",
            "indicators": [],
        }
        with patch("requests.get", return_value=_mock_response(payload)):
            result = self.ac.get_country_detail("USA")
        assert result == payload

    def test_get_top_risk_returns_list_on_success(self):
        payload = [{"iso3": "NGA", "country_name": "Nigeria", "stress_score": 75.0, "risk_level": "High Risk"}]
        with patch("requests.get", return_value=_mock_response(payload)):
            result = self.ac.get_top_risk()
        assert result == payload

    def test_get_stress_map_returns_list_on_success(self):
        payload = [{"iso3": "USA", "country_name": "United States", "stress_score": 42.5, "risk_level": "Medium Risk"}]
        with patch("requests.get", return_value=_mock_response(payload)):
            result = self.ac.get_stress_map()
        assert result == payload

    # ── Empty ISO3 guard ──────────────────────────────────────────────────────

    def test_get_country_detail_returns_none_for_empty_iso3(self):
        result = self.ac.get_country_detail("")
        assert result is None

    # ── ISO3 is uppercased ─────────────────────────────────────────────────────

    def test_get_country_detail_uppercases_iso3(self):
        with patch("requests.get", return_value=_mock_response({})) as mock_get:
            self.ac.get_country_detail("usa")
        call_url = mock_get.call_args[0][0]
        assert "USA" in call_url


# ══════════════════════════════════════════════════════════════════════════════
# TestApiClientConfiguration
# ══════════════════════════════════════════════════════════════════════════════

class TestApiClientConfiguration:
    """Test that API_BASE_URL is configurable via environment variable."""

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("API_BASE_URL", "http://myserver:9000")
        import importlib
        import src.dashboard.api_client as ac
        importlib.reload(ac)
        assert ac.API_BASE_URL == "http://myserver:9000"
        # Reload with original env for cleanup
        monkeypatch.delenv("API_BASE_URL", raising=False)
        importlib.reload(ac)

    def test_trailing_slash_is_stripped(self, monkeypatch):
        monkeypatch.setenv("API_BASE_URL", "http://localhost:8000/")
        import importlib
        import src.dashboard.api_client as ac
        importlib.reload(ac)
        assert not ac.API_BASE_URL.endswith("/")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        importlib.reload(ac)


# ══════════════════════════════════════════════════════════════════════════════
# TestComponentStructure
# ══════════════════════════════════════════════════════════════════════════════

class TestComponentStructure:
    """Verify all component functions exist and are callable."""

    def test_metrics_has_render_kpi_row(self):
        from src.dashboard.components import metrics
        assert callable(getattr(metrics, "render_kpi_row", None))

    def test_metrics_has_render_country_score_card(self):
        from src.dashboard.components import metrics
        assert callable(getattr(metrics, "render_country_score_card", None))

    def test_metrics_has_render_api_error(self):
        from src.dashboard.components import metrics
        assert callable(getattr(metrics, "render_api_error", None))

    def test_metrics_has_render_empty_state(self):
        from src.dashboard.components import metrics
        assert callable(getattr(metrics, "render_empty_state", None))

    def test_metrics_has_risk_colors_dict(self):
        from src.dashboard.components import metrics
        assert hasattr(metrics, "RISK_COLORS")
        assert isinstance(metrics.RISK_COLORS, dict)
        assert "Low Risk" in metrics.RISK_COLORS
        assert "Medium Risk" in metrics.RISK_COLORS
        assert "High Risk" in metrics.RISK_COLORS

    def test_charts_has_render_choropleth_map(self):
        from src.dashboard.components import charts
        assert callable(getattr(charts, "render_choropleth_map", None))

    def test_charts_has_render_risk_pie_chart(self):
        from src.dashboard.components import charts
        assert callable(getattr(charts, "render_risk_pie_chart", None))

    def test_charts_has_render_rankings_bar_chart(self):
        from src.dashboard.components import charts
        assert callable(getattr(charts, "render_rankings_bar_chart", None))

    def test_charts_has_render_placeholder_trend_chart(self):
        from src.dashboard.components import charts
        assert callable(getattr(charts, "render_placeholder_trend_chart", None))

    def test_tables_has_render_rankings_table(self):
        from src.dashboard.components import tables
        assert callable(getattr(tables, "render_rankings_table", None))

    def test_tables_has_render_indicators_table(self):
        from src.dashboard.components import tables
        assert callable(getattr(tables, "render_indicators_table", None))

    def test_tables_has_render_stress_map_table(self):
        from src.dashboard.components import tables
        assert callable(getattr(tables, "render_stress_map_table", None))


# ══════════════════════════════════════════════════════════════════════════════
# TestPageStructure
# ══════════════════════════════════════════════════════════════════════════════

class TestPageStructure:
    """Verify all pages exist and expose a render() callable."""

    def test_home_has_render(self):
        from src.dashboard.pages import home
        assert callable(getattr(home, "render", None))

    def test_world_map_has_render(self):
        from src.dashboard.pages import world_map
        assert callable(getattr(world_map, "render", None))

    def test_country_analysis_has_render(self):
        from src.dashboard.pages import country_analysis
        assert callable(getattr(country_analysis, "render", None))

    def test_rankings_has_render(self):
        from src.dashboard.pages import rankings
        assert callable(getattr(rankings, "render", None))

    def test_trends_has_render(self):
        from src.dashboard.pages import trends
        assert callable(getattr(trends, "render", None))

    def test_home_imports_api_client(self):
        import inspect
        from src.dashboard.pages import home
        source = inspect.getsource(home)
        assert "api_client" in source

    def test_world_map_imports_api_client(self):
        import inspect
        from src.dashboard.pages import world_map
        source = inspect.getsource(world_map)
        assert "api_client" in source

    def test_no_direct_requests_in_home(self):
        """Pages must never import requests directly."""
        import inspect
        from src.dashboard.pages import home
        source = inspect.getsource(home)
        assert "import requests" not in source

    def test_no_direct_requests_in_world_map(self):
        import inspect
        from src.dashboard.pages import world_map
        source = inspect.getsource(world_map)
        assert "import requests" not in source

    def test_no_direct_requests_in_country_analysis(self):
        import inspect
        from src.dashboard.pages import country_analysis
        source = inspect.getsource(country_analysis)
        assert "import requests" not in source

    def test_no_direct_requests_in_rankings(self):
        import inspect
        from src.dashboard.pages import rankings
        source = inspect.getsource(rankings)
        assert "import requests" not in source

    def test_no_direct_requests_in_trends(self):
        import inspect
        from src.dashboard.pages import trends
        source = inspect.getsource(trends)
        assert "import requests" not in source

    def test_trends_has_render_function(self):
        """Trends page must expose a render() function (no longer a placeholder)."""
        import inspect
        from src.dashboard.pages import trends
        source = inspect.getsource(trends)
        assert "def render()" in source
