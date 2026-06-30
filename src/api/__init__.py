"""src/api — Phase 6: FastAPI REST layer for the Global Economic Stress Monitoring Platform.

Package structure:
  app.py        — FastAPI application factory and root endpoint
  database.py   — SQLite connection dependency (get_db)
  schemas.py    — Pydantic response models
  services.py   — All SQL query logic (routers call these, never raw SQL in routers)
  routers/
    countries.py — GET /countries, GET /country/{iso3}
    stress.py    — GET /top-risk, GET /top-safe, GET /stress-map
    summary.py   — GET /global-summary

Design rules:
  - Read ONLY from data/economic_stress.db (never CSV files)
  - All SQL lives in services.py
  - Routers contain only HTTP wiring
  - Pydantic schemas on every response — no raw dicts
"""
