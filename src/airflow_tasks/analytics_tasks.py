"""
src/airflow_tasks/analytics_tasks.py
======================================

PURPOSE
-------
Airflow-callable wrapper for the Economic Stress Score Engine (Phase 4).

Contains ZERO business logic.
All scoring logic lives in src/analytics/stress_engine.py.
"""

import logging
import time

from src.analytics.stress_engine import StressEngine

logger = logging.getLogger("platform.airflow.analytics")


def run_stress_engine() -> dict:
    """
    Airflow task: compute economic stress scores → stress_scores table.

    Calls StressEngine.run() which:
      - Reads economic_data from SQLite (never from CSVs)
      - Builds complete country-year records (skips incomplete ones)
      - Applies weighted formula: raw_score
      - Normalises to 0–100: stress_score
      - Classifies: Low / Medium / High Risk
      - Persists using INSERT OR REPLACE (idempotent)

    Returns
    -------
    dict
        {"inserted": int, "errors": int} — summary pushed to XCom.

    Raises
    ------
    RuntimeError
        If the engine produces zero scores (likely missing indicators).
    """
    logger.info("=== [Task: calculate_stress_scores] START ===")
    t0 = time.perf_counter()

    engine = StressEngine()
    inserted, errors = engine.run()

    elapsed = time.perf_counter() - t0

    if inserted == 0:
        raise RuntimeError(
            "[Task: calculate_stress_scores] FAILED — StressEngine produced 0 scores. "
            "Ensure economic_data contains all 5 required indicators: "
            "GDP_GROWTH_PCT, INFLATION_PCT, UNEMPLOYMENT_PCT, "
            "INTEREST_RATE_PCT, GOVT_DEBT_PCT_GDP."
        )

    logger.info(
        "=== [Task: calculate_stress_scores] SUCCESS — "
        "%d scores written, %d errors in %.1fs ===",
        inserted, errors, elapsed,
    )
    return {"inserted": inserted, "errors": errors}
