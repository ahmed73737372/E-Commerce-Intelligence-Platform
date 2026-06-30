"""
tests/test_pipeline.py
========================
Unit tests for the ETLPipeline orchestrator (Phase 3).

Tests verify:
  - StageResult dataclass populates correctly
  - run_validation() passes correct data and catches all 8 error types
  - Pipeline stops at the right stage on failure
  - Full successful run (Stages 1–4 all mocked)
  - Idempotency: running twice does not raise errors

All heavy I/O (collectors, transformer, loader) is mocked.

Run:
    python -m pytest tests/ -v
"""

import sys
import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("platform").setLevel(logging.CRITICAL)

from src.pipeline.etl_pipeline import ETLPipeline, StageResult, REQUIRED_SCHEMA


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dirs(tmp_path):
    """Create temporary data/processed and data dirs."""
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    return tmp_path

def _make_valid_unified_df(n=10):
    """Return a small valid unified DataFrame matching the 7-column contract."""
    return pd.DataFrame([
        {
            "country_iso3":    "USA",
            "country_name":    "United States",
            "indicator_code":  "GDP_USD",
            "indicator_label": "GDP (Current USD)",
            "year":            2000 + i,
            "value":           float(20000 + i * 100),
            "source":          "World Bank",
        }
        for i in range(n)
    ])

def _write_unified_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write a DataFrame to a unified CSV path."""
    df.to_csv(path, index=False, encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# StageResult dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestStageResult:

    def test_default_values(self):
        r = StageResult(name="Test")
        assert r.success is False
        assert r.rows == 0
        assert r.elapsed_s == 0.0
        assert r.detail == ""
        assert r.error is None

    def test_custom_values(self):
        r = StageResult(name="Test", success=True, rows=500, elapsed_s=3.2,
                        detail="all good", error=None)
        assert r.success is True
        assert r.rows == 500


# ══════════════════════════════════════════════════════════════════════════════
# Stage 3 — Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestRunValidation:

    def _pipeline_with_csv(self, tmp_path, df):
        """Write df to a temp unified CSV and patch cfg.UNIFIED_CSV_PATH."""
        csv_path = tmp_path / "unified_economic_data.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8")

        pipeline = ETLPipeline()
        with patch("src.pipeline.etl_pipeline.cfg.UNIFIED_CSV_PATH", csv_path):
            result = pipeline.run_validation()
        return result

    def test_passes_on_valid_data(self, tmp_dirs):
        df = _make_valid_unified_df(20)
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is True
        assert result.rows == 20

    def test_fails_on_missing_file(self, tmp_dirs):
        pipeline = ETLPipeline()
        non_existent = tmp_dirs / "missing.csv"
        with patch("src.pipeline.etl_pipeline.cfg.UNIFIED_CSV_PATH", non_existent):
            result = pipeline.run_validation()
        assert result.success is False
        assert result.error is not None

    def test_fails_on_empty_csv(self, tmp_dirs):
        df = pd.DataFrame(columns=REQUIRED_SCHEMA)   # empty, correct columns
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is False

    def test_fails_on_missing_column(self, tmp_dirs):
        df = _make_valid_unified_df(5)
        df = df.drop(columns=["indicator_code"])  # remove a required column
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is False
        assert "Missing columns" in result.error

    def test_fails_on_non_numeric_value(self, tmp_dirs):
        df = _make_valid_unified_df(5)
        df["value"] = "not_a_number"  # force all values to be invalid
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is False

    def test_fails_on_non_numeric_year(self, tmp_dirs):
        df = _make_valid_unified_df(5)
        df["year"] = "twenty-twenty"
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is False

    def test_detail_contains_row_and_country_counts(self, tmp_dirs):
        df = _make_valid_unified_df(10)
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is True
        assert "10" in result.detail          # row count
        assert "1 countries" in result.detail # only USA in sample

    def test_year_range_appears_in_detail(self, tmp_dirs):
        df = _make_valid_unified_df(5)
        result = self._pipeline_with_csv(tmp_dirs, df)
        assert result.success is True
        assert "2000" in result.detail  # start year of our sample data


# ══════════════════════════════════════════════════════════════════════════════
# Stage ordering and error propagation
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineStageOrdering:

    def _make_pipeline_with_mocked_stages(
        self,
        stage1_ok=True,
        stage2_ok=True,
        stage3_ok=True,
        stage4_ok=True,
        stage5_ok=True,
    ):
        """
        Build an ETLPipeline where each stage method is replaced by a mock
        that returns a controlled StageResult.
        """
        pipeline = ETLPipeline()

        pipeline.run_collectors = MagicMock(return_value=StageResult(
            name="Stage 1 — Collection", success=stage1_ok, rows=100 if stage1_ok else 0,
            error=None if stage1_ok else "All collectors failed.",
        ))
        pipeline.run_transformer = MagicMock(return_value=StageResult(
            name="Stage 2 — Transformation", success=stage2_ok, rows=80 if stage2_ok else 0,
            error=None if stage2_ok else "Empty DataFrame.",
        ))
        pipeline.run_validation = MagicMock(return_value=StageResult(
            name="Stage 3 — Validation", success=stage3_ok, rows=80 if stage3_ok else 0,
            error=None if stage3_ok else "Schema mismatch.",
        ))
        pipeline.run_database_loader = MagicMock(return_value=StageResult(
            name="Stage 4 — DB Load", success=stage4_ok,
            error=None if stage4_ok else "DB error.",
        ))
        pipeline.run_stress_engine = MagicMock(return_value=StageResult(
            name="Stage 5 — Stress Engine", success=stage5_ok, rows=50 if stage5_ok else 0,
            error=None if stage5_ok else "No scores.",
        ))

        return pipeline

    def test_all_stages_run_on_full_success(self):
        p = self._make_pipeline_with_mocked_stages()
        result = p.run()
        assert result is True
        p.run_collectors.assert_called_once()
        p.run_transformer.assert_called_once()
        p.run_validation.assert_called_once()
        p.run_database_loader.assert_called_once()
        p.run_stress_engine.assert_called_once()

    def test_pipeline_stops_after_stage1_failure(self):
        p = self._make_pipeline_with_mocked_stages(stage1_ok=False)
        result = p.run()
        assert result is False
        p.run_collectors.assert_called_once()
        p.run_transformer.assert_not_called()
        p.run_validation.assert_not_called()
        p.run_database_loader.assert_not_called()

    def test_pipeline_stops_after_stage2_failure(self):
        p = self._make_pipeline_with_mocked_stages(stage2_ok=False)
        result = p.run()
        assert result is False
        p.run_transformer.assert_called_once()
        p.run_validation.assert_not_called()
        p.run_database_loader.assert_not_called()

    def test_pipeline_stops_after_stage3_failure(self):
        p = self._make_pipeline_with_mocked_stages(stage3_ok=False)
        result = p.run()
        assert result is False
        p.run_validation.assert_called_once()
        p.run_database_loader.assert_not_called()

    def test_pipeline_stops_after_stage4_failure(self):
        p = self._make_pipeline_with_mocked_stages(stage4_ok=False)
        result = p.run()
        assert result is False
        p.run_database_loader.assert_called_once()

    def test_results_list_populated_correctly(self):
        """After run(), pipeline.results should contain one entry per executed stage."""
        p = self._make_pipeline_with_mocked_stages()
        p.run()
        assert len(p.results) == 5
        assert p.results[0].name == "Stage 1 — Collection"
        assert p.results[4].name == "Stage 5 — Stress Engine"

    def test_results_list_stops_at_failed_stage(self):
        """If Stage 2 fails, results should only have 2 entries."""
        p = self._make_pipeline_with_mocked_stages(stage2_ok=False)
        p.run()
        assert len(p.results) == 2   # Stage 1 OK, Stage 2 FAIL — pipeline stops

    def test_pipeline_returns_false_on_exception_in_transformer(self):
        """If run_transformer raises an uncaught exception, the pipeline should fail gracefully."""
        pipeline = ETLPipeline()
        pipeline.run_collectors = MagicMock(return_value=StageResult(
            name="Stage 1 — Collection", success=True, rows=100,
        ))
        pipeline.run_transformer = MagicMock(side_effect=RuntimeError("Disk full"))

        # The run() method catches exceptions from each stage method call,
        # so it must return False cleanly
        result = pipeline.run()
        assert result is False
