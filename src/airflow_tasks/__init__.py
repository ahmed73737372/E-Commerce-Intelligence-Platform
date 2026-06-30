"""src/airflow_tasks — Thin Airflow task wrappers for Phase 5.

Each module in this package contains plain Python callables that:
  - Accept no arguments (compatible with PythonOperator)
  - Call exactly ONE existing project module
  - Raise exceptions on failure (Airflow marks the task as FAILED)
  - Contain ZERO business logic

Business logic lives in:
  src/collectors/   — data collection
  src/transformer/  — data standardization
  src/database/     — persistence
  src/analytics/    — stress scoring
  src/pipeline/     — orchestration helpers (e.g. validation)
"""
