"""
main.py
========
Entry point for the Global Economic Stress Monitoring Platform.

Runs the complete ETL pipeline via a single ETLPipeline.run() call.

Pipeline stages (managed internally by ETLPipeline):
  Stage 1 — Data Collection   → data/raw/*.csv
  Stage 2 — Transformation    → data/processed/unified_economic_data.csv
  Stage 3 — Validation        → schema + content checks
  Stage 4 — Database Load     → data/economic_stress.db

Usage:
    python main.py

To skip collection (re-use existing raw CSVs), comment out Stage 1
inside src/pipeline/etl_pipeline.py → ETLPipeline.run_collectors().
"""

import sys
import logging
from pathlib import Path

# Ensure project root is always on sys.path regardless of how the script is invoked
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Initialize logging FIRST ───────────────────────────────────────────────────
# Must happen before any platform module is imported (they grab loggers at import time)
from src.utils.logger import setup_logging
import config.settings as cfg

setup_logging(log_dir=str(cfg.LOGS_DIR), level=cfg.LOG_LEVEL)

# ── Import and run the pipeline ────────────────────────────────────────────────
from src.pipeline.etl_pipeline import ETLPipeline


if __name__ == "__main__":
    pipeline = ETLPipeline()
    success  = pipeline.run()
    sys.exit(0 if success else 1)
