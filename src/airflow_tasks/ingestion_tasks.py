"""
src/airflow_tasks/ingestion_tasks.py
=====================================

PURPOSE
-------
Airflow-callable wrappers for the three data collectors (Phase 1).

Each function:
  - Takes no arguments (PythonOperator convention)
  - Calls ONE collector's .run() method
  - Logs start/end/timing
  - Raises on failure (Airflow marks task FAILED automatically)

Contains ZERO business logic.
All data collection logic lives in src/collectors/.
"""

import logging
import time
from pathlib import Path

from src.collectors.world_bank_collector import WorldBankCollector
from src.collectors.imf_collector import IMFCollector
from src.collectors.fred_collector import FREDCollector

logger = logging.getLogger("platform.airflow.ingestion")


def run_world_bank_collector() -> str:
    """
    Airflow task: fetch World Bank indicators → data/raw/world_bank_raw.csv

    Returns
    -------
    str
        Absolute path of the saved CSV (used for XCom push if needed).

    Raises
    ------
    RuntimeError
        If the collector returns no data or fails to save.
    """

    logger.info("=== [Task: fetch_world_bank] START ===")
    t0 = time.perf_counter()

    saved_path = WorldBankCollector().run()

    elapsed = time.perf_counter() - t0

    if not saved_path or not Path(saved_path).exists():
        raise RuntimeError(
            "WorldBankCollector.run() did not produce a CSV file. "
            "Check logs for API errors."
        )

    rows = sum(1 for _ in open(saved_path, encoding="utf-8")) - 1
    logger.info(
        "=== [Task: fetch_world_bank] SUCCESS — %s rows saved to %s in %.1fs ===",
        f"{rows:,}", Path(saved_path).name, elapsed,
    )
    return str(saved_path)


def run_imf_collector() -> str:
    """
    Airflow task: fetch IMF indicators → data/raw/imf_raw.csv

    Returns
    -------
    str
        Absolute path of the saved CSV.

    Raises
    ------
    RuntimeError
        If the collector returns no data or fails to save.
    """

    logger.info("=== [Task: fetch_imf] START ===")
    t0 = time.perf_counter()

    saved_path = IMFCollector().run()

    elapsed = time.perf_counter() - t0

    if not saved_path or not Path(saved_path).exists():
        raise RuntimeError(
            "IMFCollector.run() did not produce a CSV file. "
            "Check logs for API errors."
        )

    rows = sum(1 for _ in open(saved_path, encoding="utf-8")) - 1
    logger.info(
        "=== [Task: fetch_imf] SUCCESS — %s rows saved to %s in %.1fs ===",
        f"{rows:,}", Path(saved_path).name, elapsed,
    )
    return str(saved_path)


def run_fred_collector() -> str:
    """
    Airflow task: fetch FRED indicators → data/raw/fred_raw.csv

    Note: if FRED_API_KEY is not set, the collector skips gracefully and
    returns an empty DataFrame. This task will raise if no file is produced,
    so a missing API key is surfaced immediately in the Airflow UI.

    Returns
    -------
    str
        Absolute path of the saved CSV.

    Raises
    ------
    RuntimeError
        If the collector returns no data or fails to save.
    """

    logger.info("=== [Task: fetch_fred] START ===")
    t0 = time.perf_counter()

    saved_path = FREDCollector().run()

    elapsed = time.perf_counter() - t0

    if not saved_path or not Path(saved_path).exists():
        raise RuntimeError(
            "FREDCollector.run() did not produce a CSV file. "
            "Ensure FRED_API_KEY is set in .env — "
            "register free at https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    rows = sum(1 for _ in open(saved_path, encoding="utf-8")) - 1
    logger.info(
        "=== [Task: fetch_fred] SUCCESS — %s rows saved to %s in %.1fs ===",
        f"{rows:,}", Path(saved_path).name, elapsed,
    )
    return str(saved_path)
