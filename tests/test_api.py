"""
tests/test_api.py
==================

Integration tests for Phase 6 — FastAPI REST layer.

STRATEGY
--------
- Uses FastAPI TestClient (no server needed — runs in-process)
- Overrides the `get_db` dependency with an in-memory SQLite database
- Seeds the in-memory DB with realistic test data before each test class
- Zero API calls, zero file I/O — completely self-contained

TEST CLASSES
------------
  TestRootEndpoint          — GET /
  TestCountriesEndpoint     — GET /countries
  TestCountryDetailEndpoint — GET /country/{iso3}
  TestTopRiskEndpoint       — GET /top-risk
  TestTopSafeEndpoint       — GET /top-safe
  TestGlobalSummaryEndpoint — GET /global-summary
  TestStressMapEndpoint     — GET /stress-map
  TestErrorCases            — 404 + empty-DB behavior

RUN
---
    python -m pytest tests/test_api.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── Project root on sys.path ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.app      import app
from src.api.database import get_db


# ══════════════════════════════════════════════════════════════════════════════
# In-memory database fixture
# ══════════════════════════════════════════════════════════════════════════════

def _build_test_db() -> sqlite3.Connection:
    """
    Create a seeded in-memory SQLite database that mirrors the real schema.

    Test data:
      Countries : USA (United States), DEU (Germany), NGA (Nigeria)
      Indicators: GDP_GROWTH_PCT, INFLATION_PCT, UNEMPLOYMENT_PCT,
                  INTEREST_RATE_PCT, GOVT_DEBT_PCT_GDP
      Scores    : USA (year=2023, stress=42.5, Medium Risk)
                  DEU (year=2023, stress=28.0, Low Risk)
                  NGA (year=2023, stress=75.0, High Risk)
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # ── Schema ────────────────────────────────────────────────────────────────
    conn.executescript("""
        CREATE TABLE countries (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            iso3  TEXT    NOT NULL UNIQUE,
            name  TEXT    NOT NULL
        );

        CREATE TABLE indicators (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            code  TEXT    NOT NULL UNIQUE,
            label TEXT    NOT NULL
        );

        CREATE TABLE economic_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id   INTEGER NOT NULL REFERENCES countries(id),
            indicator_id INTEGER NOT NULL REFERENCES indicators(id),
            year         INTEGER NOT NULL,
            value        REAL    NOT NULL,
            source       TEXT    NOT NULL,
            ingested_at  TEXT    NOT NULL,
            UNIQUE (country_id, indicator_id, year, source)
        );

        CREATE TABLE stress_scores (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id    INTEGER NOT NULL REFERENCES countries(id),
            year          INTEGER NOT NULL,
            raw_score     REAL    NOT NULL,
            stress_score  REAL    NOT NULL,
            risk_level    TEXT    NOT NULL,
            calculated_at TEXT    NOT NULL,
            UNIQUE (country_id, year)
        );
    """)

    # ── Countries ─────────────────────────────────────────────────────────────
    conn.executemany(
        "INSERT INTO countries (iso3, name) VALUES (?, ?)",
        [
            ("DEU", "Germany"),
            ("NGA", "Nigeria"),
            ("USA", "United States"),
        ],
    )

    # ── Indicators ────────────────────────────────────────────────────────────
    conn.executemany(
        "INSERT INTO indicators (code, label) VALUES (?, ?)",
        [
            ("GDP_GROWTH_PCT",    "Real GDP Growth (%)"),
            ("INFLATION_PCT",     "Inflation Rate (%)"),
            ("UNEMPLOYMENT_PCT",  "Unemployment Rate (%)"),
            ("INTEREST_RATE_PCT", "Interest Rate (%)"),
            ("GOVT_DEBT_PCT_GDP", "Government Debt (% of GDP)"),
        ],
    )

    # ── Economic data (one row per country + indicator + year) ────────────────
    usa_id = conn.execute("SELECT id FROM countries WHERE iso3='USA'").fetchone()["id"]
    deu_id = conn.execute("SELECT id FROM countries WHERE iso3='DEU'").fetchone()["id"]
    nga_id = conn.execute("SELECT id FROM countries WHERE iso3='NGA'").fetchone()["id"]

    ind = {
        row["code"]: row["id"]
        for row in conn.execute("SELECT id, code FROM indicators").fetchall()
    }

    economic_rows = [
        # USA 2023
        (usa_id, ind["GDP_GROWTH_PCT"],    2023, 2.5,  "IMF",        "2026-01-01 UTC"),
        (usa_id, ind["INFLATION_PCT"],     2023, 3.4,  "World Bank", "2026-01-01 UTC"),
        (usa_id, ind["UNEMPLOYMENT_PCT"],  2023, 3.7,  "World Bank", "2026-01-01 UTC"),
        (usa_id, ind["INTEREST_RATE_PCT"], 2023, 5.25, "FRED",       "2026-01-01 UTC"),
        (usa_id, ind["GOVT_DEBT_PCT_GDP"], 2023, 97.8, "IMF",        "2026-01-01 UTC"),
        # DEU 2023
        (deu_id, ind["GDP_GROWTH_PCT"],    2023, 0.3,  "IMF",        "2026-01-01 UTC"),
        (deu_id, ind["INFLATION_PCT"],     2023, 2.1,  "World Bank", "2026-01-01 UTC"),
        (deu_id, ind["UNEMPLOYMENT_PCT"],  2023, 3.0,  "World Bank", "2026-01-01 UTC"),
        (deu_id, ind["INTEREST_RATE_PCT"], 2023, 4.50, "FRED",       "2026-01-01 UTC"),
        (deu_id, ind["GOVT_DEBT_PCT_GDP"], 2023, 66.1, "IMF",        "2026-01-01 UTC"),
        # NGA 2023
        (nga_id, ind["GDP_GROWTH_PCT"],    2023, 2.9,  "IMF",        "2026-01-01 UTC"),
        (nga_id, ind["INFLATION_PCT"],     2023, 22.0, "World Bank", "2026-01-01 UTC"),
        (nga_id, ind["UNEMPLOYMENT_PCT"],  2023, 33.0, "World Bank", "2026-01-01 UTC"),
        (nga_id, ind["INTEREST_RATE_PCT"], 2023, 18.5, "FRED",       "2026-01-01 UTC"),
        (nga_id, ind["GOVT_DEBT_PCT_GDP"], 2023, 40.0, "IMF",        "2026-01-01 UTC"),
    ]
    conn.executemany(
        "INSERT INTO economic_data (country_id, indicator_id, year, value, source, ingested_at) VALUES (?,?,?,?,?,?)",
        economic_rows,
    )

    # ── Stress scores ─────────────────────────────────────────────────────────
    conn.executemany(
        "INSERT INTO stress_scores (country_id, year, raw_score, stress_score, risk_level, calculated_at) VALUES (?,?,?,?,?,?)",
        [
            (usa_id, 2023, 18.5, 42.5, "Medium Risk", "2026-01-01 UTC"),
            (deu_id, 2023, 10.2, 28.0, "Low Risk",    "2026-01-01 UTC"),
            (nga_id, 2023, 38.9, 75.0, "High Risk",   "2026-01-01 UTC"),
        ],
    )

    conn.commit()
    return conn


@pytest.fixture(scope="session")
def test_db():
    """Single in-memory DB shared across the test session."""
    conn = _build_test_db()
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def client(test_db):
    """
    TestClient with the get_db dependency overridden to use in-memory DB.
    Session-scoped: created once for the whole test session.
    Uses its own copy of the app so empty_client cannot pollute its overrides.
    """
    from src.api.app import app as _app
    _app.dependency_overrides[get_db] = lambda: test_db
    with TestClient(_app) as c:
        yield c
    _app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="session")
def empty_client():
    """
    TestClient backed by an empty database (no rows).
    Uses a *fresh* FastAPI app import so it never shares dependency_overrides
    with the main client fixture.
    """
    import importlib
    # Force a fresh import of the app module so we get an independent instance
    import src.api.app as _app_module
    importlib.reload(_app_module)
    _empty_app = _app_module.app

    empty_conn = sqlite3.connect(":memory:", check_same_thread=False)
    empty_conn.row_factory = sqlite3.Row
    empty_conn.executescript("""
        CREATE TABLE countries    (id INTEGER PRIMARY KEY, iso3 TEXT UNIQUE, name TEXT);
        CREATE TABLE indicators   (id INTEGER PRIMARY KEY, code TEXT UNIQUE, label TEXT);
        CREATE TABLE economic_data(id INTEGER PRIMARY KEY, country_id INT, indicator_id INT,
                                   year INT, value REAL, source TEXT, ingested_at TEXT);
        CREATE TABLE stress_scores(id INTEGER PRIMARY KEY, country_id INT, year INT,
                                   raw_score REAL, stress_score REAL, risk_level TEXT, calculated_at TEXT);
    """)
    _empty_app.dependency_overrides[get_db] = lambda: empty_conn
    with TestClient(_empty_app) as c:
        yield c
    _empty_app.dependency_overrides.clear()
    empty_conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# GET /
# ══════════════════════════════════════════════════════════════════════════════

class TestRootEndpoint:

    def test_status_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_response_has_project_key(self, client):
        data = client.get("/").json()
        assert "project" in data

    def test_response_has_status_key(self, client):
        data = client.get("/").json()
        assert "status" in data

    def test_project_name_is_correct(self, client):
        data = client.get("/").json()
        assert data["project"] == "Global Economic Stress Monitoring Platform"

    def test_status_is_running(self, client):
        data = client.get("/").json()
        assert data["status"] == "running"


# ══════════════════════════════════════════════════════════════════════════════
# GET /countries
# ══════════════════════════════════════════════════════════════════════════════

class TestCountriesEndpoint:

    def test_status_200(self, client):
        response = client.get("/countries")
        assert response.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/countries").json()
        assert isinstance(data, list)

    def test_returns_3_countries(self, client):
        data = client.get("/countries").json()
        assert len(data) == 3

    def test_each_item_has_iso3_and_name(self, client):
        data = client.get("/countries").json()
        for item in data:
            assert "iso3" in item
            assert "name" in item

    def test_iso3_codes_are_strings(self, client):
        data = client.get("/countries").json()
        for item in data:
            assert isinstance(item["iso3"], str)

    def test_countries_are_alphabetically_ordered(self, client):
        data = client.get("/countries").json()
        names = [item["name"] for item in data]
        assert names == sorted(names)

    def test_usa_present(self, client):
        data = client.get("/countries").json()
        iso3_codes = [item["iso3"] for item in data]
        assert "USA" in iso3_codes


# ══════════════════════════════════════════════════════════════════════════════
# GET /country/{iso3}
# ══════════════════════════════════════════════════════════════════════════════

class TestCountryDetailEndpoint:

    def test_status_200_for_known_country(self, client):
        response = client.get("/country/USA")
        assert response.status_code == 200

    def test_case_insensitive_lookup(self, client):
        response = client.get("/country/usa")
        assert response.status_code == 200

    def test_404_for_unknown_country(self, client):
        response = client.get("/country/ZZZ")
        assert response.status_code == 404

    def test_404_message_mentions_iso3(self, client):
        data = client.get("/country/ZZZ").json()
        assert "ZZZ" in data["detail"]

    def test_response_has_required_fields(self, client):
        data = client.get("/country/USA").json()
        for field in ("iso3", "country_name", "latest_year", "stress_score", "risk_level", "indicators"):
            assert field in data, f"Missing field: {field}"

    def test_iso3_matches_request(self, client):
        data = client.get("/country/USA").json()
        assert data["iso3"] == "USA"

    def test_country_name_is_correct(self, client):
        data = client.get("/country/USA").json()
        assert data["country_name"] == "United States"

    def test_stress_score_is_float(self, client):
        data = client.get("/country/USA").json()
        assert isinstance(data["stress_score"], float)

    def test_stress_score_value_correct(self, client):
        data = client.get("/country/USA").json()
        assert data["stress_score"] == pytest.approx(42.5)

    def test_risk_level_is_medium_for_usa(self, client):
        data = client.get("/country/USA").json()
        assert data["risk_level"] == "Medium Risk"

    def test_latest_year_is_2023(self, client):
        data = client.get("/country/USA").json()
        assert data["latest_year"] == 2023

    def test_indicators_is_list(self, client):
        data = client.get("/country/USA").json()
        assert isinstance(data["indicators"], list)

    def test_indicators_are_non_empty(self, client):
        data = client.get("/country/USA").json()
        assert len(data["indicators"]) > 0

    def test_each_indicator_has_required_fields(self, client):
        data = client.get("/country/USA").json()
        for ind in data["indicators"]:
            for field in ("code", "label", "year", "value"):
                assert field in ind, f"Missing indicator field: {field}"

    def test_indicator_code_is_uppercase(self, client):
        data = client.get("/country/USA").json()
        for ind in data["indicators"]:
            assert ind["code"] == ind["code"].upper()

    def test_high_risk_country_nigeria(self, client):
        data = client.get("/country/NGA").json()
        assert data["risk_level"] == "High Risk"
        assert data["stress_score"] == pytest.approx(75.0)

    def test_low_risk_country_germany(self, client):
        data = client.get("/country/DEU").json()
        assert data["risk_level"] == "Low Risk"
        assert data["stress_score"] == pytest.approx(28.0)


# ══════════════════════════════════════════════════════════════════════════════
# GET /top-risk
# ══════════════════════════════════════════════════════════════════════════════

class TestTopRiskEndpoint:

    def test_status_200(self, client):
        assert client.get("/top-risk").status_code == 200

    def test_returns_list(self, client):
        assert isinstance(client.get("/top-risk").json(), list)

    def test_first_item_is_highest_score(self, client):
        data = client.get("/top-risk").json()
        assert data[0]["iso3"] == "NGA"
        assert data[0]["stress_score"] == pytest.approx(75.0)

    def test_scores_are_descending(self, client):
        data = client.get("/top-risk").json()
        scores = [item["stress_score"] for item in data]
        assert scores == sorted(scores, reverse=True)

    def test_each_item_has_required_fields(self, client):
        data = client.get("/top-risk").json()
        for item in data:
            for field in ("iso3", "country_name", "stress_score", "risk_level"):
                assert field in item

    def test_limit_query_param(self, client):
        data = client.get("/top-risk?limit=1").json()
        assert len(data) == 1
        assert data[0]["iso3"] == "NGA"

    def test_404_on_empty_db(self, empty_client):
        assert empty_client.get("/top-risk").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# GET /top-safe
# ══════════════════════════════════════════════════════════════════════════════

class TestTopSafeEndpoint:

    def test_status_200(self, client):
        assert client.get("/top-safe").status_code == 200

    def test_first_item_is_lowest_score(self, client):
        data = client.get("/top-safe").json()
        assert data[0]["iso3"] == "DEU"
        assert data[0]["stress_score"] == pytest.approx(28.0)

    def test_scores_are_ascending(self, client):
        data = client.get("/top-safe").json()
        scores = [item["stress_score"] for item in data]
        assert scores == sorted(scores)

    def test_limit_query_param(self, client):
        data = client.get("/top-safe?limit=2").json()
        assert len(data) == 2

    def test_404_on_empty_db(self, empty_client):
        assert empty_client.get("/top-safe").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# GET /global-summary
# ══════════════════════════════════════════════════════════════════════════════

class TestGlobalSummaryEndpoint:

    def test_status_200(self, client):
        assert client.get("/global-summary").status_code == 200

    def test_response_has_all_fields(self, client):
        data = client.get("/global-summary").json()
        for field in (
            "total_countries",
            "average_stress_score",
            "high_risk_countries",
            "medium_risk_countries",
            "low_risk_countries",
        ):
            assert field in data, f"Missing field: {field}"

    def test_total_countries_is_3(self, client):
        data = client.get("/global-summary").json()
        assert data["total_countries"] == 3

    def test_risk_counts_sum_to_total(self, client):
        data = client.get("/global-summary").json()
        total = data["high_risk_countries"] + data["medium_risk_countries"] + data["low_risk_countries"]
        assert total == data["total_countries"]

    def test_high_risk_count_is_1(self, client):
        # Only NGA is High Risk
        data = client.get("/global-summary").json()
        assert data["high_risk_countries"] == 1

    def test_medium_risk_count_is_1(self, client):
        # Only USA is Medium Risk
        data = client.get("/global-summary").json()
        assert data["medium_risk_countries"] == 1

    def test_low_risk_count_is_1(self, client):
        # Only DEU is Low Risk
        data = client.get("/global-summary").json()
        assert data["low_risk_countries"] == 1

    def test_average_score_is_numeric(self, client):
        data = client.get("/global-summary").json()
        assert isinstance(data["average_stress_score"], (int, float))

    def test_average_score_is_correct(self, client):
        # (42.5 + 28.0 + 75.0) / 3 = 48.5
        data = client.get("/global-summary").json()
        assert data["average_stress_score"] == pytest.approx(48.5, abs=0.1)

    def test_404_on_empty_db(self, empty_client):
        assert empty_client.get("/global-summary").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# GET /stress-map
# ══════════════════════════════════════════════════════════════════════════════

class TestStressMapEndpoint:

    def test_status_200(self, client):
        assert client.get("/stress-map").status_code == 200

    def test_returns_list(self, client):
        assert isinstance(client.get("/stress-map").json(), list)

    def test_returns_all_3_countries(self, client):
        data = client.get("/stress-map").json()
        assert len(data) == 3

    def test_each_item_has_iso3_and_score_and_risk(self, client):
        data = client.get("/stress-map").json()
        for item in data:
            assert "iso3" in item
            assert "country_name" in item
            assert "stress_score" in item
            assert "risk_level" in item

    def test_ordered_alphabetically_by_name(self, client):
        data = client.get("/stress-map").json()
        names = [item["country_name"] for item in data]
        assert names == sorted(names)

    def test_all_iso3_codes_present(self, client):
        data = client.get("/stress-map").json()
        iso3_codes = {item["iso3"] for item in data}
        assert iso3_codes == {"USA", "DEU", "NGA"}

    def test_empty_db_returns_empty_list(self, empty_client):
        # /stress-map returns [] not 404 when no scores (no data ≠ error)
        data = empty_client.get("/stress-map").json()
        assert data == []
