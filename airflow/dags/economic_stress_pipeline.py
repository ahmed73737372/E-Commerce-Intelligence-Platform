"""
airflow/dags/economic_stress_pipeline.py
==========================================

DAG: economic_stress_pipeline
==============================

This DAG automates the Global Economic Stress Monitoring Platform pipeline.
It runs every day at 02:00 UTC.

DESIGN RULES
------------
- This file contains NO business logic.
- Each task calls ONE function from src/airflow_tasks/.
- All business logic remains in the existing project modules.
- The DAG is a pure orchestration graph.

TASK DEPENDENCY GRAPH
---------------------

  fetch_world_bank ─┐
                    ├─→ transform_data → validate_dataset → load_database → calculate_stress_scores
  fetch_imf ────────┤
                    │
  fetch_fred ───────┘

  fetch_world_bank, fetch_imf, fetch_fred run IN PARALLEL.
  transform_data waits for ALL THREE to complete.
  Each subsequent task runs only after its predecessor succeeds.

SCHEDULE
--------
  Cron: 0 2 * * *  (daily at 02:00 UTC)
  Catchup: False   (only run for the current day, not past missed runs)
  Max active runs: 1  (no concurrent pipeline runs)

IDEMPOTENCY
-----------
  Re-triggering the DAG for the same date is safe:
    - Collectors overwrite raw CSVs
    - Transformer overwrites unified CSV
    - Loader uses INSERT OR IGNORE
    - Stress engine uses INSERT OR REPLACE
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# ── Ensure project root is on sys.path so src.* and config.* can be imported ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Initialize project logging before importing any platform module ────────────
from src.utils.logger import setup_logging
import config.settings as cfg
setup_logging(log_dir=str(cfg.LOGS_DIR), level=cfg.LOG_LEVEL)

# ── Airflow imports ────────────────────────────────────────────────────────────
from airflow import DAG
from airflow.operators.python import PythonOperator

# ── Task callables (thin wrappers — no business logic) ─────────────────────────
from src.airflow_tasks.ingestion_tasks import (
    run_world_bank_collector,
    run_imf_collector,
    run_fred_collector,
)
from src.airflow_tasks.transformation_tasks import run_transformer
from src.airflow_tasks.database_tasks import validate_dataset, run_loader
from src.airflow_tasks.analytics_tasks import run_stress_engine

# ── DAG definition ─────────────────────────────────────────────────────────────

_DEFAULT_ARGS = {
    # Retries: 1 retry per task, 5-minute wait between attempts
    "retries":       1,
    "retry_delay":   __import__("datetime").timedelta(minutes=5),
    # Email on failure: disabled for local dev (set in Airflow Connections for prod)
    "email_on_failure":  False,
    "email_on_retry":    False,
}

with DAG(
    dag_id="economic_stress_pipeline",
    description=(
        "Daily pipeline: collect economic data → transform → validate → "
        "load into SQLite → calculate stress scores"
    ),
    schedule_interval="0 2 * * *",          # Every day at 02:00 UTC
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,                           # Don't backfill missed runs
    max_active_runs=1,                       # Never run two instances concurrently
    default_args=_DEFAULT_ARGS,
    tags=["economics", "data-engineering", "etl"],
) as dag:

    # ── Task 1a: Fetch World Bank data ─────────────────────────────────────────
    fetch_world_bank = PythonOperator(
        task_id="fetch_world_bank",
        python_callable=run_world_bank_collector,
        doc_md="""
        **fetch_world_bank**

        Calls `WorldBankCollector.run()` to download macroeconomic indicators
        from the World Bank Open Data API.

        Output: `data/raw/world_bank_raw.csv`
        """,
    )

    # ── Task 1b: Fetch IMF data ────────────────────────────────────────────────
    fetch_imf = PythonOperator(
        task_id="fetch_imf",
        python_callable=run_imf_collector,
        doc_md="""
        **fetch_imf**

        Calls `IMFCollector.run()` to download macroeconomic indicators
        from the IMF DataMapper API.

        Output: `data/raw/imf_raw.csv`
        """,
    )

    # ── Task 1c: Fetch FRED data ───────────────────────────────────────────────
    fetch_fred = PythonOperator(
        task_id="fetch_fred",
        python_callable=run_fred_collector,
        doc_md="""
        **fetch_fred**

        Calls `FREDCollector.run()` to download US economic indicators
        from the Federal Reserve Economic Data API.

        Requires `FRED_API_KEY` in `.env`.
        Output: `data/raw/fred_raw.csv`
        """,
    )

    # ── Task 2: Transform all raw CSVs → unified CSV ───────────────────────────
    transform_data = PythonOperator(
        task_id="transform_data",
        python_callable=run_transformer,
        doc_md="""
        **transform_data**

        Calls `DataTransformer.load_and_transform_all()`.
        Merges and standardizes all raw CSVs into the 7-column unified schema.

        Waits for: fetch_world_bank, fetch_imf, fetch_fred
        Output: `data/processed/unified_economic_data.csv`
        """,
    )

    # ── Task 3: Validate schema before any DB write ────────────────────────────
    validate_dataset_task = PythonOperator(
        task_id="validate_dataset",
        python_callable=validate_dataset,
        doc_md="""
        **validate_dataset**

        Runs the 8-point schema validation gate (via `ETLPipeline.run_validation()`).
        Stops the DAG run if any check fails — the database is never written
        from invalid data.

        Checks: file exists, non-empty, all 7 columns present, no null columns,
        numeric year >= 1990, numeric value, country_iso3 length = 3, uppercase codes.
        """,
    )

    # ── Task 4: Load unified CSV into SQLite ───────────────────────────────────
    load_database = PythonOperator(
        task_id="load_database",
        python_callable=run_loader,
        doc_md="""
        **load_database**

        Calls `load_to_database()` to insert unified CSV rows into SQLite.
        Uses `INSERT OR IGNORE` — safe to re-run (idempotent).

        Output: `data/economic_stress.db` (countries, indicators, economic_data tables)
        """,
    )

    # ── Task 5: Calculate and persist stress scores ────────────────────────────
    calculate_stress_scores = PythonOperator(
        task_id="calculate_stress_scores",
        python_callable=run_stress_engine,
        doc_md="""
        **calculate_stress_scores**

        Calls `StressEngine.run()` to compute a yearly Economic Stress Score
        for every country in the database.

        Formula: 0.35×Inflation + 0.25×Unemployment + 0.20×GovtDebt
                + 0.15×InterestRate − 0.15×GDPGrowth
        Normalised to 0–100. Classified as Low / Medium / High Risk.
        Uses `INSERT OR REPLACE` — idempotent.

        Output: `data/economic_stress.db` (stress_scores table)
        """,
    )

    # ── Dependency graph ───────────────────────────────────────────────────────
    #
    #   fetch_world_bank ─┐
    #                     ├──► transform_data ──► validate_dataset
    #   fetch_imf ────────┤                             │
    #                     │                        load_database
    #   fetch_fred ───────┘                             │
    #                                      calculate_stress_scores
    #
    [fetch_world_bank, fetch_imf, fetch_fred] >> transform_data
    transform_data >> validate_dataset_task >> load_database >> calculate_stress_scores
