"""
tests/test_collectors.py
==========================
Unit tests for Phase 1 collectors, the DataTransformer, and the database Loader.

All HTTP calls are mocked — no real network requests.
All database operations use an in-memory SQLite database.

Run:
    python -m pytest tests/ -v
"""

import sys
import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("platform").setLevel(logging.CRITICAL)

from src.collectors.world_bank_collector import WorldBankCollector
from src.collectors.imf_collector import IMFCollector
from src.collectors.fred_collector import FREDCollector
from src.transformer.data_transformer import DataTransformer, UNIFIED_COLUMNS
from src.database.db_manager import create_tables
from src.database.loader import _load_countries, _load_indicators, _load_economic_data


# ── 7-column unified contract ──────────────────────────────────────────────────
CONTRACT_COLS = ["country_iso3", "country_name", "indicator_code",
                 "indicator_label", "year", "value", "source"]


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_raw(tmp_path):
    d = tmp_path / "data" / "raw"
    d.mkdir(parents=True)
    return d

@pytest.fixture()
def tmp_proc(tmp_path):
    d = tmp_path / "data" / "processed"
    d.mkdir(parents=True)
    return d

@pytest.fixture()
def mem_db():
    """In-memory SQLite database with the production schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iso3 TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE indicators (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            code  TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE economic_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id   INTEGER NOT NULL REFERENCES countries(id),
            indicator_id INTEGER NOT NULL REFERENCES indicators(id),
            year         INTEGER NOT NULL,
            value        REAL    NOT NULL,
            source       TEXT    NOT NULL,
            ingested_at  TEXT    NOT NULL,
            UNIQUE (country_id, indicator_id, year, source)
        )
    """)
    conn.commit()
    yield conn
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# WorldBankCollector — 7-column contract
# ══════════════════════════════════════════════════════════════════════════════

class TestWorldBankCollector:

    def _make(self, tmp_raw):
        c = WorldBankCollector.__new__(WorldBankCollector)
        c.raw_data_dir    = tmp_raw
        c.base_url        = "https://api.worldbank.org/v2"
        c.indicators      = {"NY.GDP.MKTP.CD": "GDP_USD"}
        c.indicator_labels = {"GDP_USD": "GDP (Current USD)"}
        c.countries       = "US"
        c.start_year      = 2020
        c.end_year        = 2022
        c.timeout         = 10
        c.source_name     = "world_bank"
        c.logger          = logging.getLogger("test.wb")
        c.session         = MagicMock()
        return c

    def test_output_has_7_columns(self, tmp_raw):
        c = self._make(tmp_raw)
        records = [{"countryiso3code": "USA", "country": {"value": "United States"},
                    "date": "2021", "value": 23315.0, "unit": "USD"}]
        df = c._to_dataframe(records, "GDP_USD", "GDP (Current USD)")
        assert list(df.columns) == CONTRACT_COLS

    def test_null_values_filtered(self, tmp_raw):
        c = self._make(tmp_raw)
        records = [
            {"countryiso3code": "USA", "country": {"value": "United States"},
             "date": "2021", "value": 23315.0, "unit": "USD"},
            {"countryiso3code": "USA", "country": {"value": "United States"},
             "date": "2020", "value": None, "unit": "USD"},
        ]
        df = c._to_dataframe(records, "GDP_USD", "GDP (Current USD)")
        assert len(df) == 1
        assert df.iloc[0]["indicator_code"] == "GDP_USD"
        assert df.iloc[0]["indicator_label"] == "GDP (Current USD)"
        assert df.iloc[0]["source"] == "World Bank"

    def test_collect_with_mock(self, tmp_raw):
        c = self._make(tmp_raw)
        meta = {"page": 1, "pages": 1, "per_page": 1000, "total": 1}
        data = [{"countryiso3code": "USA", "country": {"value": "United States"},
                 "date": "2021", "value": 23000.0, "unit": "USD"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = [meta, data]
        mock_resp.raise_for_status = MagicMock()
        c._get = MagicMock(return_value=mock_resp)
        df = c.collect()
        assert not df.empty
        assert "indicator_code" in df.columns
        assert "indicator_label" in df.columns


# ══════════════════════════════════════════════════════════════════════════════
# IMFCollector — 7-column contract
# ══════════════════════════════════════════════════════════════════════════════

class TestIMFCollector:

    def _make(self, tmp_raw):
        c = IMFCollector.__new__(IMFCollector)
        c.raw_data_dir    = tmp_raw
        c.base_url        = "https://www.imf.org/external/datamapper/api/v1"
        c.indicators      = {"NGDP_RPCH": "GDP_GROWTH_PCT"}
        c.indicator_labels = {"GDP_GROWTH_PCT": "Real GDP Growth (%)"}
        c.timeout         = 10
        c.source_name     = "imf"
        c.logger          = logging.getLogger("test.imf")
        c.session         = MagicMock()
        return c

    def test_output_has_7_columns(self, tmp_raw):
        c = self._make(tmp_raw)
        country_data = {"USA": {"2021": 5.7}}
        df = c._to_dataframe(country_data, "GDP_GROWTH_PCT", "Real GDP Growth (%)")
        assert list(df.columns) == CONTRACT_COLS

    def test_country_name_blank_for_transformer_to_fill(self, tmp_raw):
        """IMF collector leaves country_name blank — transformer fills it."""
        c = self._make(tmp_raw)
        df = c._to_dataframe({"USA": {"2021": 5.7}}, "GDP_GROWTH_PCT", "Real GDP Growth (%)")
        assert df.iloc[0]["country_name"] == ""  # blank intentionally
        assert df.iloc[0]["country_iso3"] == "USA"

    def test_null_values_skipped(self, tmp_raw):
        c = self._make(tmp_raw)
        df = c._to_dataframe({"USA": {"2021": None, "2020": 4.5}},
                              "GDP_GROWTH_PCT", "Real GDP Growth (%)")
        assert len(df) == 1
        assert df.iloc[0]["year"] == 2020

    def test_collect_with_mock(self, tmp_raw):
        c = self._make(tmp_raw)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "values": {"NGDP_RPCH": {"USA": {"2021": 5.7}, "CHN": {"2021": 8.1}}}
        }
        mock_resp.raise_for_status = MagicMock()
        c._get = MagicMock(return_value=mock_resp)
        df = c.collect()
        assert len(df) == 2
        assert set(df.columns) == set(CONTRACT_COLS)


# ══════════════════════════════════════════════════════════════════════════════
# FREDCollector — 7-column contract
# ══════════════════════════════════════════════════════════════════════════════

class TestFREDCollector:

    def _make(self, tmp_raw, api_key="test_key"):
        c = FREDCollector.__new__(FREDCollector)
        c.raw_data_dir     = tmp_raw
        c.base_url         = "https://api.stlouisfed.org/fred"
        c.api_key          = api_key
        c.series           = {"UNRATE": "UNEMPLOYMENT_PCT"}
        c.indicator_labels = {"UNEMPLOYMENT_PCT": "Unemployment Rate (%)"}
        c.start_date       = "2020-01-01"
        c.end_date         = "2022-01-01"
        c.timeout          = 10
        c.source_name      = "fred"
        c.logger           = logging.getLogger("test.fred")
        c.session          = MagicMock()
        return c

    def test_output_has_7_columns(self, tmp_raw):
        c = self._make(tmp_raw)
        obs = [{"date": "2020-01-01", "value": "3.5"}]
        df = c._to_dataframe(obs, "UNEMPLOYMENT_PCT", "Unemployment Rate (%)")
        assert list(df.columns) == CONTRACT_COLS

    def test_country_hardcoded_usa(self, tmp_raw):
        c = self._make(tmp_raw)
        df = c._to_dataframe([{"date": "2021-01-01", "value": "6.0"}],
                              "UNEMPLOYMENT_PCT", "Unemployment Rate (%)")
        assert df.iloc[0]["country_iso3"] == "USA"
        assert df.iloc[0]["country_name"] == "United States"

    def test_dot_sentinel_filtered(self, tmp_raw):
        c = self._make(tmp_raw)
        obs = [{"date": "2020-01-01", "value": "3.5"},
               {"date": "2020-02-01", "value": "."},
               {"date": "2020-03-01", "value": "4.4"}]
        df = c._to_dataframe(obs, "UNEMPLOYMENT_PCT", "Unemployment Rate (%)")
        assert len(df) == 2

    def test_skipped_without_api_key(self, tmp_raw):
        c = self._make(tmp_raw, api_key="your_fred_api_key_here")
        assert c.collect().empty


# ══════════════════════════════════════════════════════════════════════════════
# DataTransformer — unified schema validation
# ══════════════════════════════════════════════════════════════════════════════

class TestDataTransformer:

    def _make(self, tmp_raw, tmp_proc):
        t = DataTransformer.__new__(DataTransformer)
        t.raw_dir     = tmp_raw
        t.proc_dir    = tmp_proc
        t.output_path = tmp_proc / "unified_economic_data.csv"
        return t

    def _valid_df(self, source="World Bank"):
        """
        Return a minimal DataFrame with 3 required stress indicators for the
        same (country, year) so the completeness filter in load_and_transform_all
        does not discard the rows.
        """
        rows = []
        for code, label in [
            ("INFLATION_PCT",    "Inflation Rate (%)"),
            ("UNEMPLOYMENT_PCT", "Unemployment Rate (%)"),
            ("GOVT_DEBT_PCT_GDP","Government Debt (% of GDP)"),
        ]:
            rows.append({
                "country_iso3":    "USA",
                "country_name":    "United States",
                "indicator_code":  code,
                "indicator_label": label,
                "year":            2021,
                "value":           5.0,
                "source":          source,
            })
        return pd.DataFrame(rows)


    def test_transform_returns_unified_columns(self, tmp_raw, tmp_proc):
        t = self._make(tmp_raw, tmp_proc)
        out = t._transform(self._valid_df(), "World Bank")
        assert list(out.columns) == UNIFIED_COLUMNS

    def test_missing_column_raises_valueerror(self, tmp_raw, tmp_proc):
        t = self._make(tmp_raw, tmp_proc)
        bad_df = pd.DataFrame([{"country_iso3": "USA", "year": 2021, "value": 1.0}])
        with pytest.raises(ValueError, match="missing required columns"):
            t._transform(bad_df, "World Bank")

    def test_fills_country_name_from_iso3(self, tmp_raw, tmp_proc):
        t = self._make(tmp_raw, tmp_proc)
        df = self._valid_df()
        df["country_name"] = ""   # blank — transformer should fill from ISO3_TO_NAME
        out = t._transform(df, "IMF")
        assert out.iloc[0]["country_name"] == "United States"

    def test_drops_pre_1990_rows(self, tmp_raw, tmp_proc):
        t = self._make(tmp_raw, tmp_proc)
        df = self._valid_df()
        df["year"] = 1985
        out = t._transform(df, "World Bank")
        assert out.empty

    def test_drops_null_values(self, tmp_raw, tmp_proc):
        t = self._make(tmp_raw, tmp_proc)
        df = self._valid_df()
        df["value"] = None
        out = t._transform(df, "World Bank")
        assert out.empty

    def test_load_and_transform_all_creates_csv(self, tmp_raw, tmp_proc):
        """Integration test: write a raw CSV, run transformer, verify output file."""
        t = self._make(tmp_raw, tmp_proc)
        # Write a minimal world_bank_raw.csv
        self._valid_df().to_csv(tmp_raw / "world_bank_raw.csv", index=False)
        out = t.load_and_transform_all()
        assert not out.empty
        assert t.output_path.exists()
        loaded = pd.read_csv(t.output_path)
        assert list(loaded.columns) == UNIFIED_COLUMNS


# ══════════════════════════════════════════════════════════════════════════════
# Database Loader — in-memory SQLite
# ══════════════════════════════════════════════════════════════════════════════

class TestDatabaseLoader:

    def _sample_unified_df(self):
        return pd.DataFrame([
            {"country_iso3": "USA", "country_name": "United States",
             "indicator_code": "GDP_USD", "indicator_label": "GDP (Current USD)",
             "year": 2021, "value": 23315.0, "source": "World Bank"},
            {"country_iso3": "DEU", "country_name": "Germany",
             "indicator_code": "INFLATION_PCT", "indicator_label": "Inflation Rate (%)",
             "year": 2021, "value": 3.1, "source": "IMF"},
        ])

    def test_load_countries_inserts_unique_rows(self, mem_db):
        df = self._sample_unified_df()
        id_map = _load_countries(mem_db, df)
        assert "USA" in id_map
        assert "DEU" in id_map
        assert isinstance(id_map["USA"], int)

    def test_load_countries_is_idempotent(self, mem_db):
        df = self._sample_unified_df()
        map1 = _load_countries(mem_db, df)
        map2 = _load_countries(mem_db, df)  # second call
        assert map1 == map2   # same ids, no new rows

    def test_load_indicators_inserts_unique_rows(self, mem_db):
        df = self._sample_unified_df()
        id_map = _load_indicators(mem_db, df)
        assert "GDP_USD" in id_map
        assert "INFLATION_PCT" in id_map

    def test_load_economic_data_inserts_rows(self, mem_db):
        df = self._sample_unified_df()
        c_map = _load_countries(mem_db, df)
        i_map = _load_indicators(mem_db, df)
        inserted, skipped = _load_economic_data(mem_db, df, c_map, i_map)
        assert inserted == 2
        assert skipped == 0

    def test_load_economic_data_is_idempotent(self, mem_db):
        """Running the loader twice must not duplicate rows."""
        df = self._sample_unified_df()
        c_map = _load_countries(mem_db, df)
        i_map = _load_indicators(mem_db, df)
        _load_economic_data(mem_db, df, c_map, i_map)
        inserted2, skipped2 = _load_economic_data(mem_db, df, c_map, i_map)
        assert inserted2 == 0   # all rows already exist
        assert skipped2 == 2    # both skipped

    def test_foreign_keys_correctly_mapped(self, mem_db):
        """Verify DB rows reference the correct country_id and indicator_id."""
        df = self._sample_unified_df()
        c_map = _load_countries(mem_db, df)
        i_map = _load_indicators(mem_db, df)
        mem_db.commit()
        _load_economic_data(mem_db, df, c_map, i_map)
        mem_db.commit()

        rows = mem_db.execute("SELECT * FROM economic_data").fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row["country_id"] in c_map.values()
            assert row["indicator_id"] in i_map.values()
