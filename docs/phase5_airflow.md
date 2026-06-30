# Phase 5 — Airflow Orchestration Layer

## Overview

Phase 5 wraps the existing pipeline inside **Apache Airflow** so it runs
automatically every day at **02:00 UTC** — no manual `python main.py` required.

Airflow is a **pure orchestration layer**. All business logic remains
unchanged in the original project modules.

---

## Architecture

```
AIRFLOW LAYER (Phase 5)          EXISTING MODULES (Phases 1–4)
─────────────────────────        ─────────────────────────────────────
economic_stress_pipeline.py  →   src/collectors/world_bank_collector.py
   fetch_world_bank              src/collectors/imf_collector.py
   fetch_imf                     src/collectors/fred_collector.py
   fetch_fred
   transform_data            →   src/transformer/data_transformer.py
   validate_dataset          →   src/pipeline/etl_pipeline.py (run_validation)
   load_database             →   src/database/loader.py
   calculate_stress_scores   →   src/analytics/stress_engine.py
```

### DAG Dependency Graph

```
fetch_world_bank ──┐
                   ├──► transform_data ──► validate_dataset ──► load_database ──► calculate_stress_scores
fetch_imf ─────────┤
                   │
fetch_fred ────────┘
```

- **fetch_world_bank**, **fetch_imf**, **fetch_fred** run in **parallel**
- **transform_data** waits for all three collectors to finish
- Remaining tasks run **sequentially** in order

---

## File Structure (Phase 5 additions)

```
d:/global/
├── airflow/
│   └── dags/
│       └── economic_stress_pipeline.py   ← The DAG definition
│
├── src/
│   └── airflow_tasks/
│       ├── __init__.py
│       ├── ingestion_tasks.py            ← Wraps WorldBankCollector, IMFCollector, FREDCollector
│       ├── transformation_tasks.py       ← Wraps DataTransformer
│       ├── database_tasks.py             ← Wraps ETLPipeline.run_validation(), load_to_database()
│       └── analytics_tasks.py            ← Wraps StressEngine
│
└── tests/
    └── test_airflow_structure.py         ← Structural tests (no server needed)
```

---

## Setup Instructions

### Step 1 — Install Apache Airflow

```powershell
# Set Airflow version constraint for Python 3.11
$env:AIRFLOW_VERSION = "2.9.2"
$env:PYTHON_VERSION = "3.11"
$env:CONSTRAINT_URL = "https://raw.githubusercontent.com/apache/airflow/constraints-$env:AIRFLOW_VERSION/constraints-$env:PYTHON_VERSION.txt"

pip install "apache-airflow==$env:AIRFLOW_VERSION" --constraint $env:CONSTRAINT_URL
```

### Step 2 — Set AIRFLOW_HOME

```powershell
# Set AIRFLOW_HOME to the airflow/ subdirectory of the project
$env:AIRFLOW_HOME = "D:\global\airflow"

# Add to your PowerShell profile for persistence:
# echo '$env:AIRFLOW_HOME = "D:\global\airflow"' >> $PROFILE
```

### Step 3 — Initialize the Database

```powershell
$env:AIRFLOW_HOME = "D:\global\airflow"
airflow db init
```

### Step 4 — Create an Admin User

```powershell
airflow users create `
    --username admin `
    --firstname Admin `
    --lastname User `
    --role Admin `
    --email admin@example.com `
    --password admin
```

### Step 5 — Configure the DAGs Folder

Airflow needs to know where your DAGs live. Edit `D:\global\airflow\airflow.cfg`:

```ini
[core]
dags_folder = D:\global\airflow\dags

# Add project root to PYTHONPATH so src.* and config.* can be imported
[core]
# On Windows, use semicolons to separate paths
```

Or set environment variables before starting Airflow:

```powershell
$env:AIRFLOW_HOME     = "D:\global\airflow"
$env:PYTHONPATH       = "D:\global"
```

### Step 6 — Start the Scheduler (in one terminal)

```powershell
$env:AIRFLOW_HOME = "D:\global\airflow"
$env:PYTHONPATH   = "D:\global"
airflow scheduler
```

### Step 7 — Start the Web Server (in another terminal)

```powershell
$env:AIRFLOW_HOME = "D:\global\airflow"
$env:PYTHONPATH   = "D:\global"
airflow webserver --port 8080
```

### Step 8 — Access the UI

Open: **http://localhost:8080**

Login with `admin` / `admin`

Find the DAG: **`economic_stress_pipeline`**

---

## Trigger the DAG Manually

```powershell
$env:AIRFLOW_HOME = "D:\global\airflow"
$env:PYTHONPATH   = "D:\global"

# Trigger a DAG run immediately (without waiting for schedule)
airflow dags trigger economic_stress_pipeline
```

---

## DAG Configuration Reference

| Setting | Value | Meaning |
|---------|-------|---------|
| `dag_id` | `economic_stress_pipeline` | Unique identifier |
| `schedule_interval` | `0 2 * * *` | Daily at 02:00 UTC |
| `catchup` | `False` | Don't run missed past dates |
| `max_active_runs` | `1` | No concurrent pipeline instances |
| `retries` | `1` | One retry per failed task |
| `retry_delay` | `5 minutes` | Wait before retry |

---

## Task Reference

| Task ID | Calls | Output |
|---------|-------|--------|
| `fetch_world_bank` | `WorldBankCollector().run()` | `data/raw/world_bank_raw.csv` |
| `fetch_imf` | `IMFCollector().run()` | `data/raw/imf_raw.csv` |
| `fetch_fred` | `FREDCollector().run()` | `data/raw/fred_raw.csv` |
| `transform_data` | `DataTransformer().load_and_transform_all()` | `data/processed/unified_economic_data.csv` |
| `validate_dataset` | `ETLPipeline().run_validation()` | (8-point gate check) |
| `load_database` | `load_to_database()` | `economic_data` table updated |
| `calculate_stress_scores` | `StressEngine().run()` | `stress_scores` table updated |

---

## Error Handling

- Any task that **raises an exception** is marked **FAILED** by Airflow
- Downstream tasks are **automatically blocked**
- The task retries **once** after a 5-minute delay
- All errors appear in the **Airflow UI task logs** and in `logs/platform.log`

### FRED API Key

If `FRED_API_KEY` is not set, `fetch_fred` will fail.
Add it to `.env` and restart the Airflow scheduler:

```ini
# .env
FRED_API_KEY=your_key_here
```

---

## Idempotency

Re-triggering the DAG for the same date is **completely safe**:

| Layer | Mechanism |
|-------|-----------|
| Collectors | Overwrite raw CSVs |
| Transformer | Overwrites unified CSV |
| Loader | `INSERT OR IGNORE` — no duplicates |
| Stress Engine | `INSERT OR REPLACE` — updates existing scores |

---

## Running Tests

Structural tests run without any Airflow server:

```powershell
# Tests that verify callable imports and delegation (always run)
python -m pytest tests/test_airflow_structure.py -v

# DAG graph tests (activate after: pip install apache-airflow)
python -m pytest tests/test_airflow_structure.py -v
# → 10 passed, 23 skipped  (before Airflow install)
# → 33 passed              (after Airflow install)

# Full test suite
python -m pytest tests/ -v
# → 82 passed (72 existing + 10 new Airflow structural tests)
```
