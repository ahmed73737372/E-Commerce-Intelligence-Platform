"""
src/airflow_tasks/database_tasks.py
=====================================

PURPOSE
-------
Airflow-callable wrappers for the validation gate and database loader
(Phases 2 and 3).

VALIDATION REUSE POLICY
-----------------------
The validate_dataset() function calls ETLPipeline.run_validation() directly.
This is the EXACT same method used in the standard pipeline run.
No validation logic is duplicated here.

Contains ZERO business logic.
Validation logic lives in src/pipeline/etl_pipeline.py.
Database loading logic lives in src/database/loader.py.
"""

import logging
import time

import config.settings as cfg
from src.pipeline.etl_pipeline import ETLPipeline
from src.database.loader import load_to_database

logger = logging.getLogger("platform.airflow.database")


def validate_dataset() -> None:
    """
    Airflow task: validate unified_economic_data.csv against 8-point schema.

    Reuses ETLPipeline.run_validation() — the same validation gate
    that runs in the standard python main.py execution.

    Checks performed (defined in ETLPipeline.run_validation):
      1. File exists
      2. Non-empty
      3. All 7 required columns present
      4. No column entirely null
      5. year is numeric and >= 1990
      6. value is numeric
      7. country_iso3 is 3 characters
      8. indicator_code is uppercase

    Raises
    ------
    RuntimeError
        If any of the 8 checks fail. Message includes the specific failure reason.
    """
    logger.info("=== [Task: validate_dataset] START ===")
    t0 = time.perf_counter()

    pipeline = ETLPipeline()
    result   = pipeline.run_validation()

    elapsed = time.perf_counter() - t0

    if not result.success:
        raise RuntimeError(
            f"[Task: validate_dataset] FAILED in {elapsed:.1f}s — {result.error}"
        )

    logger.info(
        "=== [Task: validate_dataset] SUCCESS — %s in %.1fs ===",
        result.detail, elapsed,
    )


def run_loader() -> str:
    """
    Airflow task: load unified CSV into SQLite economic_data table.

    Calls load_to_database() which:
      - Creates tables if they do not exist (idempotent)
      - Inserts unique countries and indicators into lookup tables
      - Inserts fact rows using INSERT OR IGNORE (no duplicates)

    Returns
    -------
    str
        Path to the SQLite database file.

    Raises
    ------
    RuntimeError
        If load_to_database() returns False (e.g. unified CSV missing).
    """
    logger.info("=== [Task: load_database] START ===")
    t0 = time.perf_counter()

    success = load_to_database()

    elapsed = time.perf_counter() - t0

    if not success:
        raise RuntimeError(
            "[Task: load_database] FAILED — load_to_database() returned False. "
            "Ensure validate_dataset completed successfully."
        )

    logger.info(
        "=== [Task: load_database] SUCCESS — data loaded to %s in %.1fs ===",
        cfg.DATABASE_PATH.name, elapsed,
    )
    return str(cfg.DATABASE_PATH)
