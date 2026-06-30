"""
src/database/db_manager.py
============================

PURPOSE
-------
Creates and manages the SQLite database connection and table schema.
This is the ONLY place where SQL DDL (CREATE TABLE) statements live.

DATABASE: data/economic_stress.db  (path from config/settings.py)

SCHEMA — 4 tables, aligned exactly to the 7-column unified contract:

    countries     — lookup table for country_iso3 + country_name
    indicators    — lookup table for indicator_code + indicator_label
    economic_data — fact table referencing both lookup tables
    stress_scores — Phase 4 analytics output (one score per country-year)

DESIGN DECISIONS
----------------
- SQLite is used for simplicity (no server setup, built into Python).
- Foreign keys are enabled explicitly per connection (SQLite default: OFF).
- The UNIQUE constraint on economic_data prevents duplicate rows when the
  pipeline is re-run (idempotent inserts in loader.py).
- Indexes on country_id, indicator_id, and year make common queries fast.
"""

import logging
import sqlite3
from pathlib import Path

import config.settings as cfg

logger = logging.getLogger("platform.database")

# ── SQL: Create tables ────────────────────────────────────────────────────────

_CREATE_COUNTRIES = """
CREATE TABLE IF NOT EXISTS countries (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    iso3 TEXT    NOT NULL UNIQUE,   -- e.g. "USA"
    name TEXT    NOT NULL           -- e.g. "United States"
);
"""

_CREATE_INDICATORS = """
CREATE TABLE IF NOT EXISTS indicators (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT NOT NULL UNIQUE,     -- e.g. "GDP_USD"  (canonical, uppercase)
    label TEXT NOT NULL             -- e.g. "GDP (Current USD)"
);
"""

_CREATE_ECONOMIC_DATA = """
CREATE TABLE IF NOT EXISTS economic_data (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    country_id   INTEGER NOT NULL REFERENCES countries(id),
    indicator_id INTEGER NOT NULL REFERENCES indicators(id),
    year         INTEGER NOT NULL,
    value        REAL    NOT NULL,
    source       TEXT    NOT NULL,   -- "World Bank" | "IMF" | "FRED"
    ingested_at  TEXT    NOT NULL,   -- UTC timestamp, e.g. "2026-06-22 17:00:00 UTC"
    UNIQUE (country_id, indicator_id, year, source)
);
"""

# ── SQL: Indexes ──────────────────────────────────────────────────────────────

_CREATE_INDEXES = [
    # Fast lookup by country + year (most common query pattern)
    "CREATE INDEX IF NOT EXISTS idx_data_country_year   ON economic_data (country_id, year);",
    # Fast lookup by indicator across all countries
    "CREATE INDEX IF NOT EXISTS idx_data_indicator_year ON economic_data (indicator_id, year);",
    # Fast lookup of stress scores by country
    "CREATE INDEX IF NOT EXISTS idx_stress_country_year ON stress_scores (country_id, year);",
]

# ── SQL: stress_scores table ──────────────────────────────────────────────────

_CREATE_STRESS_SCORES = """
CREATE TABLE IF NOT EXISTS stress_scores (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    country_id       INTEGER NOT NULL REFERENCES countries(id),
    year             INTEGER NOT NULL,
    raw_score        REAL    NOT NULL,   -- composite z-score (pre-sigmoid)
    stress_score     REAL    NOT NULL,   -- sigmoid-scaled 0-100
    risk_level       TEXT    NOT NULL,   -- "Low Risk" | "Medium Risk" | "High Risk"
    calculated_at    TEXT    NOT NULL,   -- UTC timestamp
    confidence_score REAL    NOT NULL DEFAULT 1.0,  -- data completeness: n_indicators/5
    UNIQUE (country_id, year)            -- one score per country per year
);
"""


def get_connection() -> sqlite3.Connection:
    """
    Open and return a connection to the SQLite database.

    - Creates the database file if it does not exist.
    - Enables foreign key enforcement (OFF by default in SQLite).
    - Uses Row factory so results can be accessed by column name.

    Returns
    -------
    sqlite3.Connection
        Caller is responsible for closing the connection.
    """
    db_path: Path = cfg.DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row          # access columns by name
    conn.execute("PRAGMA foreign_keys = ON") # enforce FK constraints
    conn.execute("PRAGMA journal_mode = WAL") # better concurrent read performance
    return conn


def create_tables() -> None:
    """
    Create all four tables and indexes if they do not already exist.
    Safe to call multiple times (idempotent — uses IF NOT EXISTS).

    Called once at the start of the loader pipeline.
    """
    logger.info("Initializing database: %s", cfg.DATABASE_PATH)

    with get_connection() as conn:
        conn.execute(_CREATE_COUNTRIES)
        conn.execute(_CREATE_INDICATORS)
        conn.execute(_CREATE_ECONOMIC_DATA)
        conn.execute(_CREATE_STRESS_SCORES)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()

    logger.info("Database schema ready (countries, indicators, economic_data, stress_scores).")


def ensure_confidence_column() -> None:
    """
    Backward-compatible migration: add confidence_score to stress_scores if absent.

    SQLite does not support IF NOT EXISTS on ALTER TABLE, so we catch the
    OperationalError that fires when the column already exists and continue.
    Safe to call on every startup — fully idempotent.
    """
    with get_connection() as conn:
        try:
            conn.execute(
                "ALTER TABLE stress_scores "
                "ADD COLUMN confidence_score REAL NOT NULL DEFAULT 1.0"
            )
            conn.commit()
            logger.info("Migration applied: stress_scores.confidence_score column added.")
        except Exception:
            # Column already exists — this is the normal case after first migration.
            pass
