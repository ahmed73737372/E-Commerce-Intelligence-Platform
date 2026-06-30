# Project Architecture — Global Economic Stress Monitoring Platform

## Phase 1 (Complete)

### Folder Structure

```
d:/global/
├── main.py                          ← Entry point (runs ingestion + transformation)
├── requirements.txt                 ← 6 dependencies (requests, pandas, dotenv, urllib3, certifi, pytest)
├── .env                             ← Private API keys  (never commit)
├── .env.example                     ← Template (safe to commit)
├── .gitignore
│
├── config/
│   └── settings.py                  ← All config constants in one place
│
├── src/
│   ├── collectors/
│   │   ├── base_collector.py        ← Abstract base: HTTP session, save_csv(), run()
│   │   ├── world_bank_collector.py  ← World Bank API (paginated, no auth)
│   │   ├── imf_collector.py         ← IMF DataMapper API (no auth)
│   │   └── fred_collector.py        ← FRED API (requires free API key)
│   ├── utils/
│   │   └── logger.py                ← setup_logging() factory (console + rotating file)
│   └── transformer.py               ← DataTransformer: unified 5-column schema
│
├── data/
│   ├── raw/                         ← *_raw.csv files from collectors
│   └── processed/                   ← unified_economic_data.csv from transformer
│
├── logs/
│   └── platform.log                 ← Rotating log (5 MB × 3 backups)
│
├── tests/
│   └── test_collectors.py           ← 14 unit tests (all HTTP mocked)
│
└── docs/
    └── phase1_architecture.md       ← This file
```

---

### OOP Class Hierarchy

```
BaseCollector (ABC)
│   - _build_session()   → requests.Session with retry adapter
│   - _get()             → GET wrapper with raise_for_status
│   - save_csv()         → writes DataFrame to data/raw/, adds ingested_at
│   - run()              → template: collect → validate → save
│
├── WorldBankCollector   → collect() + _fetch_indicator() + _to_dataframe()
├── IMFCollector         → collect() + _fetch_indicator() + _to_dataframe()
└── FREDCollector        → collect() + _fetch_series()    + _to_dataframe()
```

---

### Data Sources

| Source     | API URL                                      | Auth Required | Indicators Fetched |
|------------|----------------------------------------------|---------------|--------------------|
| World Bank | api.worldbank.org/v2                         | No            | 5                  |
| IMF        | imf.org/external/datamapper/api/v1           | No            | 5                  |
| FRED       | api.stlouisfed.org/fred                      | Yes (free key)| 7                  |

---

### Standard Schema (output of DataTransformer)

All three sources are normalized into one unified CSV with exactly 5 columns:

| Column      | Type  | Example           | Description                    |
|-------------|-------|-------------------|--------------------------------|
| `country`   | str   | `United States`   | Standardized via ISO3 mapping  |
| `indicator` | str   | `gdp_usd`         | Canonical name via alias table |
| `year`      | int   | `2021`            | 4-digit year                   |
| `value`     | float | `23315.08`        | Numeric value                  |
| `source`    | str   | `World Bank`      | Data origin                    |

Saved to: `data/processed/unified_economic_data.csv`

---

### Pipeline Flow

```
.env
  └─ config/settings.py
         ├─ WorldBankCollector.run() → data/raw/world_bank_raw.csv
         ├─ IMFCollector.run()       → data/raw/imf_raw.csv
         ├─ FREDCollector.run()      → data/raw/fred_raw.csv
         │
         └─ DataTransformer.load_and_transform_all()
                  └─ data/processed/unified_economic_data.csv
```

---

## Phase 2 (Planned — Not Implemented)

See `phase2_design.md` in the artifacts directory.

### Tables
- `countries` (id, iso3, name, region)
- `indicators` (id, code, label, unit, category)
- `economic_data` (id, country_id, indicator_id, year, value, source, ingested_at)

### Files to create
- `src/database/db_manager.py`  — connection + table creation
- `src/database/loader.py`      — CSV → SQLite insert
- `src/database/queries.py`     — common SELECT helpers
- `data/economic_stress.db`     — the SQLite database file
