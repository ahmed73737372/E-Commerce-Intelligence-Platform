"""
src/pipeline/etl_pipeline.py
==============================

WHAT IS THIS?
-------------
The ETLPipeline class is the ORCHESTRATOR of the entire platform.
It connects Phase 1, Phase 1.5, and Phase 2 in a single controlled sequence:

    Stage 1 → Collect raw data from APIs  (Phase 1)
    Stage 2 → Transform to unified schema (Phase 1.5)
    Stage 3 → Validate unified data
    Stage 4 → Load into SQLite database   (Phase 2)
    Stage 5 → Calculate Economic Stress Scores (Phase 4)

WHY A SEPARATE ORCHESTRATOR?
-----------------------------
Each phase was designed to be independently runnable (good for testing).
The ETLPipeline wraps them under one entry point with:
  - Strict execution order
  - Per-stage timing and row counts
  - Hard stop on any stage failure (no silent half-runs)
  - Idempotency guarantee (safe to rerun anytime)
  - A clean summary report at the end

IDEMPOTENCY
-----------
Running the pipeline multiple times is safe:
  - Collectors overwrite their CSVs (fresh snapshot per run)
  - Transformer overwrites unified_economic_data.csv
  - Loader uses INSERT OR IGNORE — no duplicates enter the DB

ERROR HANDLING POLICY
---------------------
  - Stage 1 (collectors): individual collector failure is logged but the
    pipeline continues. If ALL collectors fail → Stage 2 is aborted.
  - Stage 2 (transformer): failure stops the pipeline immediately.
  - Stage 3 (validation): failure stops the pipeline immediately.
  - Stage 4 (loader): failure stops the pipeline immediately.
  This ensures the DB is never loaded from invalid or incomplete data.

USAGE
-----
    from src.pipeline.etl_pipeline import ETLPipeline

    pipeline = ETLPipeline()
    success  = pipeline.run()
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

import config.settings as cfg
from src.collectors import WorldBankCollector, IMFCollector, FREDCollector
from src.transformer.data_transformer import DataTransformer, UNIFIED_COLUMNS
from src.database.loader import load_to_database
from src.analytics.stress_engine import StressEngine

logger = logging.getLogger("platform.pipeline")

# ── Stage result container ─────────────────────────────────────────────────────

@dataclass
class StageResult:
    """
    Holds the outcome of one pipeline stage.
    Used to build the final summary report.
    """
    name:        str
    success:     bool            = False
    rows:        int             = 0
    elapsed_s:   float           = 0.0
    detail:      str             = ""
    error:       Optional[str]   = None


# ── The pipeline constants ─────────────────────────────────────────────────────

# Columns that MUST exist in unified_economic_data.csv before DB load.
# This mirrors UNIFIED_COLUMNS from the transformer — kept explicit here
# so the pipeline is self-documenting.
REQUIRED_SCHEMA = [
    "country_iso3",
    "country_name",
    "indicator_code",
    "indicator_label",
    "year",
    "value",
    "source",
]

# Minimum number of rows required to consider a stage "successful"
MIN_ROWS_THRESHOLD = 1


class ETLPipeline:
    """
    Orchestrates the full ETL flow:

        Stage 1: run_collectors()       → data/raw/*.csv
        Stage 2: run_transformer()      → data/processed/unified_economic_data.csv
        Stage 3: run_validation()       → validates unified CSV schema + content
        Stage 4: run_database_loader()  → data/economic_stress.db

    Call pipeline.run() to execute all stages in order.
    Call pipeline.report() to print the summary after run().

    Attributes
    ----------
    results : list[StageResult]
        Populated after run() completes. One entry per stage.
    """

    def __init__(self) -> None:
        self.results: list[StageResult] = []

    # ══════════════════════════════════════════════════════════════════════
    # Public: main entry point
    # ══════════════════════════════════════════════════════════════════════

    def run(self) -> bool:
        """
        Execute all pipeline stages in sequence.

        Stages run in order:
          1 → 2 → 3 → 4 → 5

        If Stage 2, 3, 4, or 5 fails, execution stops immediately.
        Stage 1 collector failures are tolerated as long as at least one
        collector succeeds.

        Returns
        -------
        bool
            True if the entire pipeline completed successfully.
            False if any required stage failed.
        """
        pipeline_start = time.perf_counter()

        self._banner("ETL PIPELINE START")
        self.results.clear()

        # ── Stage 1: Ingestion ─────────────────────────────────────────
        try:
            stage1 = self.run_collectors()
        except Exception as exc:
            logger.error("Stage 1 raised an unexpected exception: %s", exc, exc_info=True)
            self.results.append(StageResult(
                name="Stage 1 — Collection", success=False, error=str(exc)
            ))
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self.results.append(stage1)
        if not stage1.success:
            logger.error("Stage 1 failed — all collectors returned no data. Stopping pipeline.")
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        # ── Stage 2: Transformation ────────────────────────────────────
        try:
            stage2 = self.run_transformer()
        except Exception as exc:
            logger.error("Stage 2 raised an unexpected exception: %s", exc, exc_info=True)
            self.results.append(StageResult(
                name="Stage 2 — Transformation", success=False, error=str(exc)
            ))
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self.results.append(stage2)
        if not stage2.success:
            logger.error("Stage 2 failed — transformer produced no output. Stopping pipeline.")
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        # ── Stage 3: Validation ────────────────────────────────────────
        try:
            stage3 = self.run_validation()
        except Exception as exc:
            logger.error("Stage 3 raised an unexpected exception: %s", exc, exc_info=True)
            self.results.append(StageResult(
                name="Stage 3 — Validation", success=False, error=str(exc)
            ))
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self.results.append(stage3)
        if not stage3.success:
            logger.error("Stage 3 failed — unified CSV failed validation. Stopping pipeline.")
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        # ── Stage 4: Database Load ─────────────────────────────────────
        try:
            stage4 = self.run_database_loader()
        except Exception as exc:
            logger.error("Stage 4 raised an unexpected exception: %s", exc, exc_info=True)
            self.results.append(StageResult(
                name="Stage 4 — DB Load", success=False, error=str(exc)
            ))
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self.results.append(stage4)
        if not stage4.success:
            logger.error("Stage 4 failed — database load did not complete. Stopping pipeline.")
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        # ── Stage 5: Stress Score Engine ──────────────────────────────────
        try:
            stage5 = self.run_stress_engine()
        except Exception as exc:
            logger.error("Stage 5 raised an unexpected exception: %s", exc, exc_info=True)
            self.results.append(StageResult(
                name="Stage 5 — Stress Engine", success=False, error=str(exc)
            ))
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self.results.append(stage5)
        if not stage5.success:
            logger.error("Stage 5 failed — stress score calculation failed. Stopping pipeline.")
            self._print_report(time.perf_counter() - pipeline_start)
            return False

        self._print_report(time.perf_counter() - pipeline_start)
        self._banner("ETL PIPELINE COMPLETE ✔")
        return True

    # ══════════════════════════════════════════════════════════════════════
    # Stage 1 — Data Collection
    # ══════════════════════════════════════════════════════════════════════

    def run_collectors(self) -> StageResult:
        """
        Run all three data collectors.

        Each collector is run independently — a single collector failure
        does not stop the others. The stage fails only if NO collector
        produces output.

        Returns
        -------
        StageResult
            success=True  if at least one collector wrote a CSV file.
            rows          = total records collected across all sources.
        """
        self._log_stage_start(1, "Data Collection")
        t0 = time.perf_counter()

        collectors = [
            WorldBankCollector(),
            IMFCollector(),
            FREDCollector(),
        ]

        successes   = 0
        total_rows  = 0
        detail_parts = []

        for collector in collectors:
            name = collector.source_name
            try:
                t_c = time.perf_counter()
                saved_path = collector.run()
                elapsed_c  = time.perf_counter() - t_c

                if saved_path and saved_path.exists():
                    # Count rows in the saved CSV (minus the header)
                    rows = sum(1 for _ in open(saved_path, encoding="utf-8")) - 1
                    total_rows += rows
                    successes  += 1
                    detail_parts.append(f"{name}: {rows:,} rows ({elapsed_c:.1f}s)")
                    logger.info(
                        "  [STAGE 1] %-15s OK  → %s rows in %.1fs",
                        name, f"{rows:,}", elapsed_c,
                    )
                else:
                    detail_parts.append(f"{name}: SKIPPED/FAILED")
                    logger.warning("  [STAGE 1] %-15s SKIPPED or FAILED", name)

            except Exception as exc:
                detail_parts.append(f"{name}: ERROR ({exc})")
                logger.error("  [STAGE 1] %-15s ERROR: %s", name, exc, exc_info=True)

        elapsed = time.perf_counter() - t0
        success = successes > 0

        result = StageResult(
            name      = "Stage 1 — Collection",
            success   = success,
            rows      = total_rows,
            elapsed_s = elapsed,
            detail    = " | ".join(detail_parts),
        )

        if success:
            logger.info(
                "[STAGE 1] Complete: %d/%d collectors OK, %s total rows, %.1fs",
                successes, len(collectors), f"{total_rows:,}", elapsed,
            )
        else:
            result.error = "All collectors failed or were skipped."

        return result

    # ══════════════════════════════════════════════════════════════════════
    # Stage 2 — Transformation
    # ══════════════════════════════════════════════════════════════════════

    def run_transformer(self) -> StageResult:
        """
        Run the DataTransformer to merge all raw CSVs into the unified CSV.

        Fails if the transformer returns an empty DataFrame.

        Returns
        -------
        StageResult
            success=True  if unified_economic_data.csv was produced with > 0 rows.
            rows          = number of rows in the unified CSV.
        """
        self._log_stage_start(2, "Data Transformation")
        t0 = time.perf_counter()

        try:
            transformer = DataTransformer()
            unified_df  = transformer.load_and_transform_all()
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("[STAGE 2] Transformer raised an exception: %s", exc, exc_info=True)
            return StageResult(
                name      = "Stage 2 — Transformation",
                success   = False,
                elapsed_s = elapsed,
                error     = str(exc),
            )

        elapsed = time.perf_counter() - t0

        if unified_df.empty:
            logger.error("[STAGE 2] Transformer returned an empty DataFrame.")
            return StageResult(
                name      = "Stage 2 — Transformation",
                success   = False,
                elapsed_s = elapsed,
                error     = "Empty DataFrame returned by transformer.",
            )

        rows = len(unified_df)
        sources = unified_df["source"].nunique() if "source" in unified_df.columns else "?"
        logger.info(
            "[STAGE 2] Complete: %s rows from %s sources in %.1fs",
            f"{rows:,}", sources, elapsed,
        )

        return StageResult(
            name      = "Stage 2 — Transformation",
            success   = True,
            rows      = rows,
            elapsed_s = elapsed,
            detail    = f"{sources} sources merged",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Stage 3 — Schema Validation
    # ══════════════════════════════════════════════════════════════════════

    def run_validation(self) -> StageResult:
        """
        Validate that unified_economic_data.csv conforms to the required schema
        BEFORE loading into the database.

        Checks performed:
          1. File exists and is non-empty
          2. All 7 required columns are present
          3. No required column is entirely null
          4. 'year' column contains only integers >= 1990
          5. 'value' column contains only numeric values
          6. 'country_iso3' is always 3 characters
          7. 'indicator_code' is always uppercase

        This is the GATE between the transformer and the database loader.
        A failed validation stops the pipeline before any DB write occurs.

        Returns
        -------
        StageResult
            success=True  if all checks pass.
            detail        = summary of validation results (pass counts).
        """
        self._log_stage_start(3, "Schema Validation")
        t0 = time.perf_counter()

        unified_path = cfg.UNIFIED_CSV_PATH
        errors: list[str] = []
        warnings: list[str] = []

        # ── Check 1: File exists ───────────────────────────────────────
        if not unified_path.exists():
            elapsed = time.perf_counter() - t0
            msg = f"Unified CSV not found: {unified_path}"
            logger.error("[STAGE 3] %s", msg)
            return StageResult(
                name="Stage 3 — Validation", success=False,
                elapsed_s=elapsed, error=msg,
            )

        df = pd.read_csv(unified_path, low_memory=False)

        # ── Check 2: Non-empty ─────────────────────────────────────────
        if df.empty:
            errors.append("Unified CSV is empty.")

        # ── Check 3: All required columns present ──────────────────────
        missing_cols = [c for c in REQUIRED_SCHEMA if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing columns: {missing_cols}")

        if errors:
            # Cannot continue further checks without the columns
            elapsed = time.perf_counter() - t0
            for e in errors:
                logger.error("[STAGE 3] FAIL — %s", e)
            return StageResult(
                name="Stage 3 — Validation", success=False,
                elapsed_s=elapsed, error="; ".join(errors),
            )

        total_rows = len(df)

        # ── Check 4: No column is entirely null ───────────────────────
        for col in REQUIRED_SCHEMA:
            null_count = df[col].isna().sum()
            if null_count == total_rows:
                errors.append(f"Column '{col}' is entirely null.")
            elif null_count > 0:
                warnings.append(f"Column '{col}' has {null_count:,} nulls.")

        # ── Check 5: year >= 1990, numeric ────────────────────────────
        year_col = pd.to_numeric(df["year"], errors="coerce")
        invalid_years = year_col.isna().sum()
        old_years = (year_col < 1990).sum()
        if invalid_years > 0:
            errors.append(f"{invalid_years:,} rows have non-numeric 'year'.")
        if old_years > 0:
            warnings.append(f"{old_years:,} rows have year < 1990 (will be filtered by transformer).")

        # ── Check 6: value is numeric ──────────────────────────────────
        value_col = pd.to_numeric(df["value"], errors="coerce")
        invalid_values = value_col.isna().sum()
        if invalid_values > 0:
            errors.append(f"{invalid_values:,} rows have non-numeric 'value'.")

        # ── Check 7: country_iso3 is 3 characters ─────────────────────
        bad_iso3 = df["country_iso3"].astype(str).str.strip().str.len() != 3
        bad_iso3_count = bad_iso3.sum()
        if bad_iso3_count > 0:
            warnings.append(f"{bad_iso3_count:,} rows have country_iso3 != 3 chars.")

        # ── Check 8: indicator_code is uppercase ──────────────────────
        bad_codes = df["indicator_code"].astype(str).str.strip()
        not_upper = (bad_codes != bad_codes.str.upper()).sum()
        if not_upper > 0:
            warnings.append(f"{not_upper:,} rows have lowercase indicator_code.")

        elapsed = time.perf_counter() - t0

        # ── Emit warnings ──────────────────────────────────────────────
        for w in warnings:
            logger.warning("[STAGE 3] WARNING — %s", w)

        # ── Final verdict ──────────────────────────────────────────────
        if errors:
            for e in errors:
                logger.error("[STAGE 3] FAIL — %s", e)
            return StageResult(
                name="Stage 3 — Validation", success=False,
                rows=total_rows, elapsed_s=elapsed,
                error="; ".join(errors),
            )

        unique_countries   = df["country_iso3"].nunique()
        unique_indicators  = df["indicator_code"].nunique()
        unique_sources     = df["source"].nunique()
        year_range         = f"{int(year_col.min())}–{int(year_col.max())}"

        detail = (
            f"{total_rows:,} rows | {unique_countries} countries | "
            f"{unique_indicators} indicators | {unique_sources} sources | "
            f"years {year_range}"
        )

        logger.info("[STAGE 3] Validation PASSED — %s (%.1fs)", detail, elapsed)

        return StageResult(
            name="Stage 3 — Validation", success=True,
            rows=total_rows, elapsed_s=elapsed, detail=detail,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Stage 4 — Database Load
    # ══════════════════════════════════════════════════════════════════════

    def run_database_loader(self) -> StageResult:
        """
        Load the validated unified CSV into the SQLite database.

        Delegates entirely to src/database/loader.load_to_database().
        That function:
          - Creates tables if not exist
          - Inserts countries and indicators into lookup tables
          - Inserts fact rows using INSERT OR IGNORE (idempotent)

        Returns
        -------
        StageResult
            success=True  if load_to_database() returned True.
        """
        self._log_stage_start(4, "Database Load")
        t0 = time.perf_counter()

        try:
            success = load_to_database()
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("[STAGE 4] Loader raised an exception: %s", exc, exc_info=True)
            return StageResult(
                name="Stage 4 — DB Load", success=False,
                elapsed_s=elapsed, error=str(exc),
            )

        elapsed = time.perf_counter() - t0

        if not success:
            return StageResult(
                name="Stage 4 — DB Load", success=False,
                elapsed_s=elapsed,
                error="load_to_database() returned False.",
            )

        logger.info("[STAGE 4] Complete: data loaded to %s in %.1fs",
                    cfg.DATABASE_PATH.name, elapsed)

        return StageResult(
            name="Stage 4 — DB Load", success=True,
            elapsed_s=elapsed,
            detail=f"DB: {cfg.DATABASE_PATH.name}",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Stage 5 — Economic Stress Score Engine
    # ══════════════════════════════════════════════════════════════════════

    def run_stress_engine(self) -> StageResult:
        """
        Run the Economic Stress Score Engine.

        Delegates to StressEngine.run() which:
          - Reads economic_data from SQLite (never CSVs)
          - Builds complete country-year records
          - Calculates raw stress scores using the weighted formula
          - Normalises scores to 0–100 via Min-Max scaling
          - Classifies each score into Low / Medium / High Risk
          - Persists results to the stress_scores table (idempotent)

        Returns
        -------
        StageResult
            success=True  if at least 1 score was inserted or updated.
            rows          = number of scores written.
        """
        self._log_stage_start(5, "Stress Score Engine")
        t0 = time.perf_counter()

        try:
            engine = StressEngine()
            inserted, errors = engine.run()
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("[STAGE 5] Stress engine raised an exception: %s", exc, exc_info=True)
            return StageResult(
                name="Stage 5 — Stress Engine", success=False,
                elapsed_s=elapsed, error=str(exc),
            )

        elapsed = time.perf_counter() - t0

        if inserted == 0:
            return StageResult(
                name="Stage 5 — Stress Engine", success=False,
                elapsed_s=elapsed,
                error="Stress engine produced 0 scores. Check that the DB has "
                      "all required indicators (GDP_GROWTH_PCT, INFLATION_PCT, "
                      "UNEMPLOYMENT_PCT, INTEREST_RATE_PCT, GOVT_DEBT_PCT_GDP).",
            )

        logger.info(
            "[STAGE 5] Complete: %d scores written, %d errors, %.1fs",
            inserted, errors, elapsed,
        )

        return StageResult(
            name="Stage 5 — Stress Engine", success=True,
            rows=inserted, elapsed_s=elapsed,
            detail=f"{inserted} country-year scores → stress_scores table",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Reporting
    # ══════════════════════════════════════════════════════════════════════

    def _print_report(self, total_elapsed: float) -> None:
        """
        Print a structured summary table of all stage results to the log.

        Example output:
        ┌─────────────────────────────────────────────────────────────────┐
        │  PIPELINE REPORT                                                │
        ├──────────────────────────┬────────┬──────────┬─────────────────┤
        │  Stage                   │ Status │   Rows   │  Time           │
        ├──────────────────────────┼────────┼──────────┼─────────────────┤
        │  Stage 1 — Collection    │   OK   │  34,200  │  45.3s          │
        │  Stage 2 — Transformation│   OK   │  32,100  │   2.1s          │
        │  Stage 3 — Validation    │   OK   │  32,100  │   0.3s          │
        │  Stage 4 — DB Load       │   OK   │       —  │   1.8s          │
        ├──────────────────────────┴────────┴──────────┴─────────────────┤
        │  Total time: 49.5s                                             │
        └─────────────────────────────────────────────────────────────────┘
        """
        W = 65
        line  = "─" * W
        dline = "═" * W

        logger.info(dline)
        logger.info("  PIPELINE REPORT")
        logger.info(line)
        logger.info("  %-26s  %-7s  %-10s  %s",
                    "Stage", "Status", "Rows", "Time")
        logger.info(line)

        for r in self.results:
            status = "  OK  " if r.success else " FAIL "
            rows   = f"{r.rows:>8,}" if r.rows else "        —"
            logger.info(
                "  %-26s  [%s]  %s  %.1fs",
                r.name, status, rows, r.elapsed_s,
            )
            if r.detail:
                logger.info("    ↳  %s", r.detail)
            if r.error:
                logger.error("    ✗  %s", r.error)

        logger.info(line)

        overall = all(r.success for r in self.results)
        status_word = "SUCCESS ✔" if overall else "FAILED ✗"
        logger.info(
            "  Overall: %-10s  |  Total time: %.1fs",
            status_word, total_elapsed,
        )
        logger.info("  DB  : %s", cfg.DATABASE_PATH)
        logger.info("  CSV : %s", cfg.UNIFIED_CSV_PATH)
        logger.info("  Log : %s", cfg.LOGS_DIR / "platform.log")
        logger.info(dline)

    # ══════════════════════════════════════════════════════════════════════
    # Private helpers
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _log_stage_start(number: int, name: str) -> None:
        logger.info("─" * 60)
        logger.info("  STAGE %d — %s", number, name)
        logger.info("─" * 60)

    @staticmethod
    def _banner(message: str) -> None:
        logger.info("═" * 60)
        logger.info("  %s", message)
        logger.info("═" * 60)
