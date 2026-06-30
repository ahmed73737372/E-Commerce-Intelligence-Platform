"""
src/airflow_tasks/transformation_tasks.py
==========================================

PURPOSE
-------
Airflow-callable wrapper for the DataTransformer (Phase 1.5).

Contains ZERO business logic.
All transformation logic lives in src/transformer/data_transformer.py.
"""

import logging
import time

import config.settings as cfg
from src.transformer.data_transformer import DataTransformer

logger = logging.getLogger("platform.airflow.transformation")


def run_transformer() -> str:
    """
    Airflow task: merge raw CSVs → data/processed/unified_economic_data.csv

    Calls DataTransformer.load_and_transform_all() which:
      - Reads world_bank_raw.csv, imf_raw.csv, fred_raw.csv
      - Validates 7-column contract for each
      - Fills missing country names from ISO3 mapping
      - Drops nulls and pre-1990 rows
      - Merges all sources into one unified CSV

    Returns
    -------
    str
        Absolute path of the saved unified CSV.

    Raises
    ------
    RuntimeError
        If the transformer produces an empty DataFrame.
    """
    logger.info("=== [Task: transform_data] START ===")
    t0 = time.perf_counter()

    transformer = DataTransformer()
    unified_df  = transformer.load_and_transform_all()

    elapsed = time.perf_counter() - t0

    if unified_df.empty:
        raise RuntimeError(
            "DataTransformer returned an empty DataFrame. "
            "Ensure at least one collector task produced valid output."
        )

    rows    = len(unified_df)
    sources = unified_df["source"].nunique() if "source" in unified_df.columns else "?"
    logger.info(
        "=== [Task: transform_data] SUCCESS — %s rows from %s sources "
        "saved to %s in %.1fs ===",
        f"{rows:,}", sources, cfg.UNIFIED_CSV_PATH.name, elapsed,
    )
    return str(cfg.UNIFIED_CSV_PATH)
