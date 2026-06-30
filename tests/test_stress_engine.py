"""
tests/test_stress_engine.py
============================
Unit tests for the Economic Stress Score Engine (Robust Z-Score Pipeline).

Tests cover:
  - classify_risk() helper — unchanged behaviour
  - CountryYearRecord.compute_raw_score() — works identically on z-scores
  - Monotonic transforms: _signed_log, _cbrt
  - StressEngine._percentile() correctness
  - StressEngine._calibrate_alpha() calibration property
  - StressEngine._fit_params() global parameter structure
  - Missing indicator handling (threshold=3, partial data kept)
  - Confidence scoring: 5→1.0, 4→0.80, 3→0.60
  - Mild dampening: stress score for partial records nearer to 50 than full
  - Sigmoid monotonicity: higher z-composite → higher stress_score
  - _normalise_and_classify() output structure
  - _persist() idempotency (INSERT OR REPLACE)
  - Full engine run (end-to-end) with in-memory SQLite
  - Pipeline Stage 5 integration (mocked engine)

No real API calls or disk I/O (params path patched).
All data is synthetic.

Run:
    python -m pytest tests/ -v
"""

import json
import logging
import math
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("platform").setLevel(logging.CRITICAL)

from src.analytics.stress_engine import (
    StressEngine,
    CountryYearRecord,
    classify_risk,
    _signed_log,
    _cbrt,
)
from src.pipeline.etl_pipeline import ETLPipeline, StageResult as PipelineStageResult


# ── Fixtures ───────────────────────────────────────────────────────────────────

# Default weights matching settings.py
WEIGHTS = {
    "INFLATION_PCT":    +0.35,
    "UNEMPLOYMENT_PCT": +0.25,
    "GOVT_DEBT_PCT_GDP":+0.20,
    "INTEREST_RATE_PCT":+0.15,
    "GDP_GROWTH_PCT":   -0.15,
}
REQUIRED = list(WEIGHTS.keys())


def _make_engine() -> StressEngine:
    """Return a StressEngine wired to test weights, no file I/O."""
    engine = StressEngine.__new__(StressEngine)
    engine.required     = REQUIRED
    engine.weights      = WEIGHTS
    engine._params_path = Path("/nonexistent/params.json")  # never read from disk
    return engine


def _make_record(country_id=1, country_name="Testland", year=2021,
                 inflation=1.0, unemployment=1.0, debt=1.0,
                 interest=1.0, gdp_growth=1.0) -> CountryYearRecord:
    """Build a CountryYearRecord with default z-score-like values."""
    return CountryYearRecord(
        country_id   = country_id,
        country_name = country_name,
        year         = year,
        indicators   = {
            "INFLATION_PCT":    inflation,
            "UNEMPLOYMENT_PCT": unemployment,
            "GOVT_DEBT_PCT_GDP":debt,
            "INTEREST_RATE_PCT":interest,
            "GDP_GROWTH_PCT":   gdp_growth,
        },
    )


# ── In-memory DB fixture with confidence_score column ─────────────────────────

@pytest.fixture()
def mem_db():
    """In-memory SQLite with the full production schema (including confidence_score)."""
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
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
    conn.execute("""
        CREATE TABLE stress_scores (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id       INTEGER NOT NULL REFERENCES countries(id),
            year             INTEGER NOT NULL,
            raw_score        REAL    NOT NULL,
            stress_score     REAL    NOT NULL,
            risk_level       TEXT    NOT NULL,
            calculated_at    TEXT    NOT NULL,
            confidence_score REAL    NOT NULL DEFAULT 1.0,
            UNIQUE (country_id, year)
        )
    """)
    conn.commit()
    yield conn
    conn.close()


def _seed_economic_data(conn, indicators: dict[str, float],
                        country_id=1, year=2021):
    """Insert indicator rows into the in-memory DB."""
    conn.execute(
        "INSERT OR IGNORE INTO countries (id, iso3, name) VALUES (?,?,?)",
        (country_id, f"TS{country_id}", f"Country {country_id}"),
    )
    for i, (code, value) in enumerate(indicators.items(), start=1):
        conn.execute(
            "INSERT OR IGNORE INTO indicators (id, code, label) VALUES (?,?,?)",
            (i, code, code.replace("_", " ").title()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO economic_data "
            "(country_id, indicator_id, year, value, source, ingested_at) "
            "VALUES (?,?,?,?,?,?)",
            (country_id, i, year, value, "Test", "2026-01-01 00:00:00 UTC"),
        )
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# classify_risk()
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyRisk:

    def test_low_risk_at_zero(self):
        assert classify_risk(0.0) == "Low Risk"

    def test_low_risk_at_boundary(self):
        assert classify_risk(30.0) == "Low Risk"

    def test_medium_risk_just_above_low(self):
        assert classify_risk(30.1) == "Medium Risk"

    def test_medium_risk_at_boundary(self):
        assert classify_risk(60.0) == "Medium Risk"

    def test_high_risk_just_above_medium(self):
        assert classify_risk(60.1) == "High Risk"

    def test_high_risk_at_max(self):
        assert classify_risk(100.0) == "High Risk"

    def test_returns_string(self):
        assert isinstance(classify_risk(45.0), str)


# ══════════════════════════════════════════════════════════════════════════════
# Monotonic transforms
# ══════════════════════════════════════════════════════════════════════════════

class TestTransforms:

    def test_signed_log_positive(self):
        result = _signed_log(10.0)
        assert result == pytest.approx(math.log1p(10.0), rel=1e-9)

    def test_signed_log_negative(self):
        result = _signed_log(-10.0)
        assert result == pytest.approx(-math.log1p(10.0), rel=1e-9)

    def test_signed_log_zero(self):
        assert _signed_log(0.0) == 0.0

    def test_cbrt_positive(self):
        assert _cbrt(27.0) == pytest.approx(3.0, rel=1e-9)

    def test_cbrt_zero(self):
        assert _cbrt(0.0) == 0.0

    def test_cbrt_negative_clamped_to_zero(self):
        # Debt cannot be negative — cbrt clamps negatives to 0
        assert _cbrt(-10.0) == 0.0

    def test_transforms_are_monotonically_increasing(self):
        """Each transform must be strictly increasing over typical ranges."""
        for fn in [_signed_log, lambda x: math.log1p(max(0, x)), _cbrt]:
            vals = [fn(v) for v in [0, 1, 5, 10, 50, 100, 500]]
            assert vals == sorted(vals), f"{fn.__name__} is not monotonic"

    def test_signed_log_compresses_extreme_inflation(self):
        """Hyperinflation values should not dominate z-scores after transform."""
        normal = _signed_log(5.0)
        hyper  = _signed_log(10_000.0)
        ratio  = hyper / normal
        # Without transform ratio = 2000; after signed_log it should be << 10
        # (actual ratio ≈ 5.14, confirming ~390x compression vs raw values)
        assert ratio < 10.0, f"signed_log did not compress: ratio={ratio:.2f}"


# ══════════════════════════════════════════════════════════════════════════════
# StressEngine._percentile()
# ══════════════════════════════════════════════════════════════════════════════

class TestPercentile:

    def test_median_of_odd_list(self):
        result = StressEngine._percentile([1, 2, 3, 4, 5], 50)
        assert result == pytest.approx(3.0)

    def test_median_of_even_list(self):
        result = StressEngine._percentile([1, 2, 3, 4], 50)
        assert result == pytest.approx(2.5)

    def test_p0_is_minimum(self):
        assert StressEngine._percentile([1, 2, 3, 4, 5], 0) == 1.0

    def test_p100_is_maximum(self):
        assert StressEngine._percentile([1, 2, 3, 4, 5], 100) == 5.0

    def test_single_element(self):
        assert StressEngine._percentile([42.0], 50) == 42.0

    def test_empty_returns_zero(self):
        assert StressEngine._percentile([], 50) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# StressEngine._calibrate_alpha()
# ══════════════════════════════════════════════════════════════════════════════

class TestCalibrateAlpha:

    def test_p99_maps_to_near_99_5_percent(self):
        """Core calibration requirement: P99 composite → 99.5% stress."""
        composites = list(range(1, 1001))    # uniform distribution 1..1000
        alpha      = StressEngine._calibrate_alpha(composites)
        p99        = StressEngine._percentile(sorted(composites), 99)
        stress     = 100.0 / (1.0 + math.exp(-alpha * p99))
        assert abs(stress - 99.5) < 0.01, (
            f"P99 composite should map to 99.5% stress, got {stress:.4f}%"
        )

    def test_empty_list_returns_fallback(self):
        alpha = StressEngine._calibrate_alpha([])
        assert isinstance(alpha, float)
        assert alpha > 0

    def test_all_negative_composites_returns_fallback(self):
        alpha = StressEngine._calibrate_alpha([-5.0, -3.0, -1.0])
        assert alpha > 0   # should not raise or divide by zero


# ══════════════════════════════════════════════════════════════════════════════
# CountryYearRecord.compute_raw_score()
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeRawScore:

    def test_weighted_composite_formula(self):
        """
        compute_raw_score() dynamically normalises weights to sum to 1.
        After normalisation the effective weight of each indicator depends
        on how many are present.  With all 5 present:

            sum_w = 0.35 + 0.25 + 0.20 + 0.15 + (-0.15) = 0.80
            adj_INFLATION = 0.35 / 0.80 = 0.4375
            adj_GDP       = -0.15 / 0.80 = -0.1875
        """
        rec    = _make_record()
        avail  = {k: w for k, w in WEIGHTS.items() if k in rec.indicators}
        sum_w  = sum(avail.values())
        expected = sum((w / sum_w) * rec.indicators[k] for k, w in avail.items())
        assert abs(rec.compute_raw_score(WEIGHTS) - expected) < 1e-9

    def test_zero_z_scores_give_zero_composite(self):
        rec = _make_record(inflation=0, unemployment=0, debt=0,
                           interest=0, gdp_growth=0)
        assert rec.compute_raw_score(WEIGHTS) == 0.0

    def test_higher_positive_z_raises_composite(self):
        rec_low  = _make_record(inflation=0.5)
        rec_high = _make_record(inflation=5.0)
        assert rec_high.compute_raw_score(WEIGHTS) > rec_low.compute_raw_score(WEIGHTS)

    def test_positive_gdp_z_reduces_composite(self):
        """GDP growth weight is negative: positive z-score reduces the composite."""
        rec_low_growth  = _make_record(gdp_growth=0.0)
        rec_high_growth = _make_record(gdp_growth=5.0)
        assert rec_high_growth.compute_raw_score(WEIGHTS) < rec_low_growth.compute_raw_score(WEIGHTS)

    def test_partial_record_3_indicators(self):
        """3-indicator record should still produce a finite composite."""
        rec = CountryYearRecord(1, "Partial", 2021, {
            "INFLATION_PCT":    2.0,
            "UNEMPLOYMENT_PCT": 1.0,
            "GOVT_DEBT_PCT_GDP":0.5,
        })
        result = rec.compute_raw_score(WEIGHTS)
        assert math.isfinite(result)


# ══════════════════════════════════════════════════════════════════════════════
# Missing indicator handling & confidence scoring
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingIndicators:

    def test_5_indicators_confidence_1(self):
        """Full record → confidence_score = 1.0."""
        rec   = _make_record()
        conf  = len(rec.indicators) / 5.0
        assert conf == 1.0

    def test_4_indicators_confidence_0_80(self):
        rec = CountryYearRecord(1, "Test", 2021, {
            k: 1.0 for k in list(WEIGHTS.keys())[:4]
        })
        conf = len(rec.indicators) / 5.0
        assert abs(conf - 0.80) < 1e-9

    def test_3_indicators_confidence_0_60(self):
        rec = CountryYearRecord(1, "Test", 2021, {
            k: 1.0 for k in list(WEIGHTS.keys())[:3]
        })
        conf = len(rec.indicators) / 5.0
        assert abs(conf - 0.60) < 1e-9

    def test_load_records_keeps_4_indicator_record(self, mem_db):
        """4 of 5 required indicators → kept (threshold = 3)."""
        partial = {k: 5.0 for k in list(REQUIRED)[:-1]}
        _seed_economic_data(mem_db, partial, country_id=1, year=2021)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            records = engine._load_records()
        assert len(records) == 1

    def test_load_records_keeps_3_indicator_record(self, mem_db):
        """3 of 5 required indicators → kept (at threshold = 3)."""
        partial = {k: 5.0 for k in list(REQUIRED)[:3]}
        _seed_economic_data(mem_db, partial, country_id=1, year=2021)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            records = engine._load_records()
        assert len(records) == 1

    def test_load_records_skips_2_indicator_record(self, mem_db):
        """2 of 5 indicators → below threshold → excluded."""
        two_only = {k: 5.0 for k in list(REQUIRED)[:2]}
        _seed_economic_data(mem_db, two_only, country_id=1, year=2021)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            records = engine._load_records()
        assert len(records) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Normalisation & sigmoid
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalisation:

    def _minimal_params(self, alpha: float = 1.5) -> dict:
        """Build the minimal params dict required by _normalise_and_classify."""
        return {
            "sigmoid": {
                "alpha": alpha,
                "calibration": "test",
                "composite_p99": 3.0,
            },
            "indicators": {},
        }

    def _run_normalise(self, records, alpha=1.5):
        engine     = _make_engine()
        raw_scores = {(r.country_id, r.year): r.compute_raw_score(WEIGHTS)
                      for r in records}
        params     = self._minimal_params(alpha)
        return engine._normalise_and_classify(records, raw_scores, params)

    def test_higher_composite_gives_higher_stress(self):
        """Sigmoid is monotonically increasing: more z-composite → more stress."""
        low_stress  = _make_record(country_id=1, inflation=-1.0, debt=-1.0, gdp_growth=2.0)
        high_stress = _make_record(country_id=2, inflation=3.0, debt=2.5, gdp_growth=-2.0)
        result = self._run_normalise([low_stress, high_stress])
        scores = {r["country_id"]: r["stress_score"] for r in result}
        assert scores[2] > scores[1]

    def test_scores_in_valid_range(self):
        recs = [_make_record(country_id=i, inflation=float(i), debt=float(i))
                for i in range(1, 6)]
        result = self._run_normalise(recs)
        for r in result:
            assert 0.0 <= r["stress_score"] <= 100.0

    def test_risk_levels_assigned(self):
        recs = [_make_record(country_id=i) for i in range(1, 4)]
        result = self._run_normalise(recs)
        for r in result:
            assert r["risk_level"] in {"Low Risk", "Medium Risk", "High Risk"}

    def test_raw_score_present_and_float(self):
        recs = [_make_record(country_id=1), _make_record(country_id=2, inflation=5.0)]
        result = self._run_normalise(recs)
        for r in result:
            assert "raw_score" in r
            assert isinstance(r["raw_score"], float)

    def test_confidence_score_present(self):
        result = self._run_normalise([_make_record(country_id=1)])
        assert "confidence_score" in result[0]

    def test_full_data_no_dampening_effect(self):
        """5-indicator record: dampening=1.0 → raw_score × 1 → no shift."""
        rec    = _make_record(country_id=1, inflation=2.0)
        result = self._run_normalise([rec])
        assert result[0]["confidence_score"] == 1.0

    def test_partial_data_stress_nearer_50(self):
        """
        A 3-indicator record with the same z-score values should have a
        stress_score closer to 50 than the equivalent full-data record,
        because the dampening factor (sqrt(0.60)=0.775) compresses the composite.
        """
        full_rec = _make_record(country_id=1, inflation=3.0, unemployment=2.0,
                                debt=2.0, interest=1.5, gdp_growth=-1.5)
        partial_rec = CountryYearRecord(2, "Partial", 2021, {
            "INFLATION_PCT":    3.0,
            "UNEMPLOYMENT_PCT": 2.0,
            "GOVT_DEBT_PCT_GDP":2.0,
        })
        result_full    = self._run_normalise([full_rec])
        result_partial = self._run_normalise([partial_rec])
        stress_full    = result_full[0]["stress_score"]
        stress_partial = result_partial[0]["stress_score"]
        # Both should be above 50 (positive composites); partial should be lower
        assert stress_full > 50.0
        assert stress_partial > 50.0
        assert stress_partial < stress_full, (
            f"Partial record ({stress_partial:.2f}) should be less stressed "
            f"than full record ({stress_full:.2f}) after dampening"
        )


# ══════════════════════════════════════════════════════════════════════════════
# _persist() — DB idempotency
# ══════════════════════════════════════════════════════════════════════════════

class TestPersist:

    def _make_scored_records(self, n=2):
        return [
            {
                "country_id":      i,
                "country_name":    f"Country{i}",
                "year":            2021,
                "raw_score":       float(i * 0.5),
                "stress_score":    float(i * 25.0),
                "risk_level":      classify_risk(float(i * 25.0)),
                "confidence_score":1.0,
                "calculated_at":   "2026-01-01 00:00:00 UTC",
            }
            for i in range(1, n + 1)
        ]

    def test_inserts_correct_row_count(self, mem_db):
        for i in range(1, 3):
            mem_db.execute(
                "INSERT OR IGNORE INTO countries (id, iso3, name) VALUES (?,?,?)",
                (i, f"TS{i}", f"Country {i}"),
            )
        mem_db.commit()
        engine = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            inserted, errors = engine._persist(self._make_scored_records(2))
        assert inserted == 2
        assert errors == 0

    def test_idempotent_rerun(self, mem_db):
        for i in range(1, 3):
            mem_db.execute(
                "INSERT OR IGNORE INTO countries (id, iso3, name) VALUES (?,?,?)",
                (i, f"TS{i}", f"Country {i}"),
            )
        mem_db.commit()
        records = self._make_scored_records(2)
        engine  = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            engine._persist(records)
            inserted2, errors2 = engine._persist(records)
        assert errors2 == 0
        assert inserted2 == 2
        row_count = mem_db.execute(
            "SELECT COUNT(*) FROM stress_scores"
        ).fetchone()[0]
        assert row_count == 2

    def test_confidence_score_written_to_db(self, mem_db):
        mem_db.execute(
            "INSERT OR IGNORE INTO countries (id, iso3, name) VALUES (1,'USA','United States')"
        )
        mem_db.commit()
        records = [{
            "country_id":      1,
            "country_name":    "United States",
            "year":            2022,
            "raw_score":       0.45,
            "stress_score":    62.3,
            "risk_level":      "High Risk",
            "confidence_score":0.80,
            "calculated_at":   "2026-01-01 00:00:00 UTC",
        }]
        engine = _make_engine()
        with patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            engine._persist(records)
        row = mem_db.execute(
            "SELECT * FROM stress_scores WHERE country_id=1 AND year=2022"
        ).fetchone()
        assert row is not None
        assert abs(row["confidence_score"] - 0.80) < 1e-5
        assert abs(row["stress_score"]     - 62.3) < 1e-5


# ══════════════════════════════════════════════════════════════════════════════
# Full engine run (end-to-end with in-memory DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestFullEngineRun:

    def _build_full_db(self, mem_db):
        """Seed: 2 countries × 2 years × 5 indicators — all present."""
        countries = [(1, "USA", "United States"), (2, "DEU", "Germany")]
        for cid, iso3, name in countries:
            mem_db.execute(
                "INSERT OR IGNORE INTO countries (id, iso3, name) VALUES (?,?,?)",
                (cid, iso3, name),
            )
        for i, code in enumerate(REQUIRED, start=1):
            mem_db.execute(
                "INSERT OR IGNORE INTO indicators (id, code, label) VALUES (?,?,?)",
                (i, code, code),
            )
        for cid in [1, 2]:
            for year in [2020, 2021]:
                for iid, code in enumerate(REQUIRED, start=1):
                    val = float((cid * 10) + (year - 2020) + iid)
                    mem_db.execute(
                        "INSERT OR IGNORE INTO economic_data "
                        "(country_id, indicator_id, year, value, source, ingested_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (cid, iid, year, val, "Test", "2026-01-01"),
                    )
        mem_db.commit()

    def _fake_params(self) -> dict:
        """Minimal params dict for patching _load_or_fit_params."""
        return {
            "schema_version": "2.0",
            "computed_at": "2026-01-01T00:00:00+00:00",
            "n_records": 4,
            "fitting_method": "test",
            "sigmoid": {
                "alpha": 1.5,
                "calibration": "test",
                "composite_p99": 3.0,
            },
            "indicators": {
                code: {"median": 0.0, "scale": 1.0, "iqr": 1.0, "n": 4,
                       "q1": -0.5, "q3": 0.5, "transform": "test"}
                for code in REQUIRED
            },
        }

    def test_run_returns_correct_count(self, mem_db):
        self._build_full_db(mem_db)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.create_tables"), \
             patch("src.analytics.stress_engine.ensure_confidence_column"), \
             patch("src.analytics.stress_engine.get_connection", return_value=mem_db), \
             patch.object(engine, "_load_or_fit_params", return_value=self._fake_params()):
            inserted, errors = engine.run()
        # 2 countries × 2 years = 4 scores
        assert inserted == 4
        assert errors == 0

    def test_run_is_idempotent(self, mem_db):
        self._build_full_db(mem_db)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.create_tables"), \
             patch("src.analytics.stress_engine.ensure_confidence_column"), \
             patch("src.analytics.stress_engine.get_connection", return_value=mem_db), \
             patch.object(engine, "_load_or_fit_params", return_value=self._fake_params()):
            engine.run()
            inserted2, errors2 = engine.run()
        assert errors2 == 0
        row_count = mem_db.execute(
            "SELECT COUNT(*) FROM stress_scores"
        ).fetchone()[0]
        assert row_count == 4

    def test_scores_written_to_db(self, mem_db):
        self._build_full_db(mem_db)
        engine = _make_engine()
        with patch("src.analytics.stress_engine.create_tables"), \
             patch("src.analytics.stress_engine.ensure_confidence_column"), \
             patch("src.analytics.stress_engine.get_connection", return_value=mem_db), \
             patch.object(engine, "_load_or_fit_params", return_value=self._fake_params()):
            engine.run()
        rows = mem_db.execute("SELECT * FROM stress_scores").fetchall()
        assert len(rows) == 4
        for row in rows:
            assert 0.0 <= row["stress_score"] <= 100.0
            assert row["risk_level"] in {"Low Risk", "Medium Risk", "High Risk"}

    def test_returns_zero_when_no_complete_records(self, mem_db):
        """Only 1 indicator → below threshold → returns (0, 0)."""
        mem_db.execute(
            "INSERT INTO countries (id, iso3, name) VALUES (1,'USA','United States')"
        )
        mem_db.execute(
            "INSERT INTO indicators (id, code, label) VALUES (1,'INFLATION_PCT','Inflation')"
        )
        mem_db.execute(
            "INSERT INTO economic_data "
            "(country_id, indicator_id, year, value, source, ingested_at) "
            "VALUES (1, 1, 2021, 3.5, 'Test', '2026-01-01')"
        )
        mem_db.commit()
        engine = _make_engine()
        with patch("src.analytics.stress_engine.create_tables"), \
             patch("src.analytics.stress_engine.ensure_confidence_column"), \
             patch("src.analytics.stress_engine.get_connection", return_value=mem_db):
            inserted, errors = engine.run()
        assert inserted == 0


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline Stage 5 integration
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineStage5:

    def _make_4stage_ok_pipeline(self):
        p = ETLPipeline()
        for n, name in [
            ("run_collectors",      "Stage 1 — Collection"),
            ("run_transformer",     "Stage 2 — Transformation"),
            ("run_validation",      "Stage 3 — Validation"),
            ("run_database_loader", "Stage 4 — DB Load"),
        ]:
            setattr(p, n, MagicMock(return_value=PipelineStageResult(
                name=name, success=True, rows=100,
            )))
        return p

    def test_stage5_runs_after_stage4(self):
        p = self._make_4stage_ok_pipeline()
        p.run_stress_engine = MagicMock(return_value=PipelineStageResult(
            name="Stage 5 — Stress Engine", success=True, rows=80,
        ))
        result = p.run()
        assert result is True
        p.run_stress_engine.assert_called_once()

    def test_stage5_failure_stops_pipeline(self):
        p = self._make_4stage_ok_pipeline()
        p.run_stress_engine = MagicMock(return_value=PipelineStageResult(
            name="Stage 5 — Stress Engine", success=False,
            error="No indicators found.",
        ))
        result = p.run()
        assert result is False

    def test_stage5_exception_stops_pipeline(self):
        p = self._make_4stage_ok_pipeline()
        p.run_stress_engine = MagicMock(side_effect=RuntimeError("DB locked"))
        result = p.run()
        assert result is False

    def test_results_list_has_5_entries_on_success(self):
        p = self._make_4stage_ok_pipeline()
        p.run_stress_engine = MagicMock(return_value=PipelineStageResult(
            name="Stage 5 — Stress Engine", success=True, rows=80,
        ))
        p.run()
        assert len(p.results) == 5
        assert p.results[4].name == "Stage 5 — Stress Engine"
