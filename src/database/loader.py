"""
src/database/loader.py
========================

PURPOSE
-------
The LOADER is the final step in the pipeline. It reads the unified CSV
produced by the transformer and inserts every row into the SQLite database.

It is the only module that writes to the database.
It reads only from: data/processed/unified_economic_data.csv

IDEMPOTENCY
-----------
The database has a UNIQUE constraint on (country_id, indicator_id, year, source).
This means:
  - If a row already exists, it is IGNORED (not duplicated, not updated).
  - Re-running the full pipeline will not corrupt the database.
  - This is implemented using INSERT OR IGNORE.

LOADING STRATEGY
----------------
1. create_tables()          — ensure schema exists
2. _load_countries()        — insert unique countries, build iso3 → id map
3. _load_indicators()       — insert unique indicators, build code → id map
4. _load_economic_data()    — insert fact rows using FK ids
5. Report counts

FOREIGN KEY MAPPING
-------------------
The unified CSV uses human-readable strings (country_iso3, indicator_code).
The database uses integer IDs. The loader resolves this mapping using
in-memory dicts built in steps 2 and 3, so no JOIN is needed during insert.
"""

import logging
from datetime import datetime, timezone

import pandas as pd

import config.settings as cfg
from src.database.db_manager import create_tables, get_connection

logger = logging.getLogger("platform.loader")


def load_to_database() -> bool:
    """
    Main entry point: read unified_economic_data.csv and load into SQLite.

    Returns True on success, False if the unified CSV was not found or is empty.
    """
    unified_path = cfg.UNIFIED_CSV_PATH

    if not unified_path.exists():
        logger.error(
            "Unified CSV not found: %s\n"
            "Run the transformer first (Stage 2 in main.py).",
            unified_path,
        )
        return False

    # ── Read the unified CSV ───────────────────────────────────────────
    logger.info("Reading unified CSV: %s", unified_path.name)
    df = pd.read_csv(unified_path, low_memory=False)

    if df.empty:
        logger.error("Unified CSV is empty — nothing to load.")
        return False

    logger.info("Unified CSV loaded: %d rows", len(df))

    # ── Ensure schema exists ───────────────────────────────────────────
    create_tables()

    with get_connection() as conn:
        # ── STEP 0: Purge stale rows from previous runs ────────────────
        # The transformer filters years on new data only. Old runs may have
        # inserted pre-2000 or post-2024 rows that survive via INSERT OR IGNORE.
        # This purge enforces the valid window before every load cycle.
        _purge_stale_rows(conn)
        _fix_country_names(conn, df)

        # ── Insert data in three steps ─────────────────────────────────
        country_id_map   = _load_countries(conn, df)
        indicator_id_map = _load_indicators(conn, df)
        inserted, skipped = _load_economic_data(conn, df, country_id_map, indicator_id_map)
        conn.commit()

    logger.info(
        "Load complete: %d rows inserted, %d rows skipped (already exist).",
        inserted,
        skipped,
    )
    return True


# ── Private step functions ────────────────────────────────────────────────────

VALID_YEAR_MIN = 2000
VALID_YEAR_MAX = 2024  # Always the last completed calendar year


def _purge_stale_rows(conn) -> None:
    """
    Remove rows that fall outside the valid year window.
    This enforces idempotency even across pipeline runs that predate
    the year-filtering logic in the transformer.

    Deletes:
      - economic_data where year < 2000 or year > 2024
      - stress_scores where year < 2000 or year > 2024
    Also removes orphaned countries (name='nan') that have no economic_data.
    """
    r1 = conn.execute(
        "DELETE FROM economic_data WHERE year < ? OR year > ?",
        (VALID_YEAR_MIN, VALID_YEAR_MAX),
    ).rowcount
    r2 = conn.execute(
        "DELETE FROM stress_scores WHERE year < ? OR year > ?",
        (VALID_YEAR_MIN, VALID_YEAR_MAX),
    ).rowcount
    # Remove countries that are regional aggregates (name='nan') AND
    # have no economic_data rows (safe: leaves any with real data intact)
    r3 = conn.execute(
        """
        DELETE FROM countries
        WHERE (name = 'nan' OR name = '' OR name IS NULL)
        AND id NOT IN (SELECT DISTINCT country_id FROM economic_data)
        """
    ).rowcount
    conn.commit()
    logger.info(
        "Purge complete: %d economic_data rows removed, %d stress_scores removed, "
        "%d orphan/nan countries removed.",
        r1, r2, r3,
    )


def _fix_country_names(conn, df: pd.DataFrame) -> None:
    """
    Update country names in the DB that are stored as 'nan' with the
    correct name from the current unified CSV (which has the mapping).
    This repairs countries inserted before the ISO3_TO_NAME mapping was complete.
    """
    name_map = (
        df[["country_iso3", "country_name"]]
        .dropna(subset=["country_iso3", "country_name"])
        .drop_duplicates(subset=["country_iso3"])
        .set_index("country_iso3")["country_name"]
        .to_dict()
    )
    fixed = 0
    for iso3, name in name_map.items():
        name_str = str(name).strip()
        if name_str and name_str.lower() != "nan":
            cursor = conn.execute(
                "UPDATE countries SET name = ? WHERE iso3 = ? AND (name = 'nan' OR name = '')",
                (name_str, str(iso3).strip()),
            )
            fixed += cursor.rowcount
    conn.commit()
    if fixed:
        logger.info("Fixed %d country names that were stored as 'nan'.", fixed)

def _load_countries(conn, df: pd.DataFrame) -> dict[str, int]:
    """
    Insert all unique countries into the countries table.
    Returns a mapping: { "USA": 1, "CHN": 2, ... }
    """
    unique_countries = (
        df[["country_iso3", "country_name"]]
        .drop_duplicates(subset=["country_iso3"])
        .dropna(subset=["country_iso3"])
    )

    for _, row in unique_countries.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO countries (iso3, name) VALUES (?, ?)",
            (str(row["country_iso3"]).strip(), str(row["country_name"]).strip()),
        )

    # Build id map from database (includes pre-existing rows)
    rows = conn.execute("SELECT id, iso3 FROM countries").fetchall()
    id_map = {row["iso3"]: row["id"] for row in rows}

    logger.info("Countries table: %d unique countries.", len(id_map))
    return id_map


def _load_indicators(conn, df: pd.DataFrame) -> dict[str, int]:
    """
    Insert all unique indicators into the indicators table.
    Returns a mapping: { "GDP_USD": 1, "INFLATION_PCT": 2, ... }
    """
    unique_indicators = (
        df[["indicator_code", "indicator_label"]]
        .drop_duplicates(subset=["indicator_code"])
        .dropna(subset=["indicator_code"])
    )

    for _, row in unique_indicators.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO indicators (code, label) VALUES (?, ?)",
            (str(row["indicator_code"]).strip(), str(row["indicator_label"]).strip()),
        )

    rows = conn.execute("SELECT id, code FROM indicators").fetchall()
    id_map = {row["code"]: row["id"] for row in rows}

    logger.info("Indicators table: %d unique indicators.", len(id_map))
    return id_map


def _load_economic_data(
    conn,
    df: pd.DataFrame,
    country_id_map: dict[str, int],
    indicator_id_map: dict[str, int],
) -> tuple[int, int]:
    """
    Insert all fact rows into economic_data using INSERT OR IGNORE.
    Rows whose country or indicator is not in the lookup maps are skipped
    (this should not happen if the transformer and collectors are correct).

    Returns (inserted_count, skipped_count).
    """
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    inserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        country_id   = country_id_map.get(str(row["country_iso3"]).strip())
        indicator_id = indicator_id_map.get(str(row["indicator_code"]).strip())

        if country_id is None or indicator_id is None:
            logger.debug(
                "Skipping row — unmapped country '%s' or indicator '%s'.",
                row["country_iso3"],
                row["indicator_code"],
            )
            skipped += 1
            continue

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO economic_data
                (country_id, indicator_id, year, value, source, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                country_id,
                indicator_id,
                int(row["year"]),
                float(row["value"]),
                str(row["source"]).strip(),
                ingested_at,
            ),
        )

        if cursor.rowcount == 1:
            inserted += 1
        else:
            skipped += 1

    return inserted, skipped
