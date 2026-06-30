"""
src/api/services.py
====================

ALL SQL queries for the Phase 6 API layer.

RULES
-----
- Routers must NEVER contain raw SQL — they call service functions only
- Services receive a sqlite3.Connection and return typed Python objects
- All queries are SELECT only — this layer is read-only
- If a country is not found, functions return None (routers raise 404)

FUNCTION CATALOGUE
------------------
  get_all_countries(db)        → list[dict]
  get_country_by_iso3(db, iso3)→ dict | None
  get_country_detail(db, iso3) → dict | None
  get_top_risk(db, limit)      → list[dict]
  get_top_safe(db, limit)      → list[dict]
  get_global_summary(db)       → dict | None
  get_stress_map(db)           → list[dict]

SQL PATTERNS USED
-----------------
  Latest year per country: correlated subquery
      WHERE ss.year = (SELECT MAX(ss2.year) FROM stress_scores ss2
                       WHERE ss2.country_id = ss.country_id)

  Latest value per indicator per country: correlated subquery on economic_data
"""

import sqlite3
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# Countries
# ══════════════════════════════════════════════════════════════════════════════

def get_all_countries(db: sqlite3.Connection) -> list[dict]:
    """
    Return countries that have at least one stress score, ordered alphabetically.
    Excludes any entries with blank, null, or 'nan' names (IMF aggregates).
    """
    rows = db.execute(
        """
        SELECT DISTINCT c.iso3, c.name
        FROM   countries c
        JOIN   stress_scores ss ON ss.country_id = c.id
        WHERE  c.name IS NOT NULL
          AND  TRIM(c.name) != ''
          AND  LOWER(c.name) != 'nan'
        ORDER  BY c.name
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_country_by_iso3(db: sqlite3.Connection, iso3: str) -> Optional[dict]:
    """
    Return basic country metadata for a given ISO3 code, or None if not found.
    Case-insensitive lookup (UPPER comparison).
    """
    row = db.execute(
        "SELECT id, iso3, name FROM countries WHERE UPPER(iso3) = UPPER(?)",
        (iso3,),
    ).fetchone()
    return dict(row) if row else None


def get_country_detail(db: sqlite3.Connection, iso3: str) -> Optional[dict]:
    """
    Return full country profile:
      - Country metadata (iso3, name)
      - Latest stress score, year, risk_level (None if no scores exist)
      - Latest value per economic indicator (latest year available per indicator)

    Returns None if the country does not exist in the countries table.
    """
    # ── 1. Resolve country ─────────────────────────────────────────────────
    country = get_country_by_iso3(db, iso3)
    if country is None:
        return None

    country_id = country["id"]

    # ── 2. Latest stress score ─────────────────────────────────────────────
    score_row = db.execute(
        """
        SELECT year, stress_score, risk_level
        FROM   stress_scores
        WHERE  country_id = ?
        ORDER  BY year DESC
        LIMIT  1
        """,
        (country_id,),
    ).fetchone()

    # ── 3. Latest indicator value per indicator code ───────────────────────
    #
    # Pattern: for each indicator_id, pick the row with MAX(year).
    # AVG(value) handles cases where multiple sources reported the same
    # (country, indicator, year) — consistent with StressEngine behaviour.
    #
    indicator_rows = db.execute(
        """
        SELECT  i.code,
                i.label,
                ed.year,
                AVG(ed.value) AS value
        FROM    economic_data ed
        JOIN    indicators    i  ON ed.indicator_id = i.id
        WHERE   ed.country_id = ?
          AND   ed.year = (
                    SELECT MAX(ed2.year)
                    FROM   economic_data ed2
                    WHERE  ed2.country_id   = ed.country_id
                      AND  ed2.indicator_id = ed.indicator_id
                )
        GROUP   BY i.code, i.label, ed.year
        ORDER   BY i.label
        """,
        (country_id,),
    ).fetchall()

    return {
        "iso3":         country["iso3"],
        "country_name": country["name"],
        "latest_year":  score_row["year"]         if score_row else None,
        "stress_score": score_row["stress_score"]  if score_row else None,
        "risk_level":   score_row["risk_level"]    if score_row else None,
        "indicators":   [dict(r) for r in indicator_rows],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Stress Rankings
# ══════════════════════════════════════════════════════════════════════════════

def _latest_scores_query(db: sqlite3.Connection, order: str, limit: int) -> list[dict]:
    """
    Internal helper: query latest stress score per country, ordered by score.

    Parameters
    ----------
    order : str   "DESC" for highest first (top risk), "ASC" for lowest first (top safe)
    limit : int   Maximum rows to return
    """
    # Use a correlated subquery to select only the most recent year per country.
    # This is safe and correct even when different countries have different max years.
    sql = f"""
        SELECT  c.iso3,
                c.name          AS country_name,
                ss.year,
                ss.stress_score,
                ss.risk_level
        FROM    stress_scores ss
        JOIN    countries     c  ON ss.country_id = c.id
        WHERE   ss.year = (
                    SELECT MAX(ss2.year)
                    FROM   stress_scores ss2
                    WHERE  ss2.country_id = ss.country_id
                )
        ORDER   BY ss.stress_score {order}
        LIMIT   ?
    """
    rows = db.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_top_risk(db: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Top N countries ordered by highest (worst) stress score."""
    return _latest_scores_query(db, "DESC", limit)


def get_top_safe(db: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Top N countries ordered by lowest (best) stress score."""
    return _latest_scores_query(db, "ASC", limit)


# ══════════════════════════════════════════════════════════════════════════════
# Global Summary
# ══════════════════════════════════════════════════════════════════════════════

def get_global_summary(db: sqlite3.Connection) -> Optional[dict]:
    """
    Aggregate statistics across all countries using their latest stress score.

    Returns None only if the stress_scores table is completely empty.
    """
    row = db.execute(
        """
        SELECT
            COUNT(*)                                                    AS total_countries,
            ROUND(AVG(ss.stress_score), 2)                             AS average_stress_score,
            SUM(CASE WHEN ss.risk_level = 'High Risk'   THEN 1 ELSE 0 END) AS high_risk_countries,
            SUM(CASE WHEN ss.risk_level = 'Medium Risk' THEN 1 ELSE 0 END) AS medium_risk_countries,
            SUM(CASE WHEN ss.risk_level = 'Low Risk'    THEN 1 ELSE 0 END) AS low_risk_countries
        FROM stress_scores ss
        WHERE ss.year = (
            SELECT MAX(ss2.year)
            FROM   stress_scores ss2
            WHERE  ss2.country_id = ss.country_id
        )
        """
    ).fetchone()

    if row is None or row["total_countries"] == 0:
        return None

    return dict(row)


# ══════════════════════════════════════════════════════════════════════════════
# Stress Map (all countries — intended for dashboard)
# ══════════════════════════════════════════════════════════════════════════════

def get_stress_map(db: sqlite3.Connection) -> list[dict]:
    """
    Latest stress score for every country that has been scored.
    Ordered alphabetically by country name.
    Excludes entries with invalid/nan country names.
    """
    rows = db.execute(
        """
        SELECT  c.iso3,
                c.name          AS country_name,
                ss.year,
                ss.stress_score,
                ss.risk_level
        FROM    stress_scores ss
        JOIN    countries     c  ON ss.country_id = c.id
        WHERE   ss.year = (
                    SELECT MAX(ss2.year)
                    FROM   stress_scores ss2
                    WHERE  ss2.country_id = ss.country_id
                )
          AND   c.name IS NOT NULL
          AND   TRIM(c.name) != ''
          AND   LOWER(c.name) != 'nan'
        ORDER   BY c.name
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Historical Trend Queries (for Trends page)
# ══════════════════════════════════════════════════════════════════════════════

def get_country_history(db: sqlite3.Connection, iso3: str) -> list[dict]:
    """
    Return all stress scores for a given country ordered by year.
    Used by the Trends page for per-country line charts.
    """
    rows = db.execute(
        """
        SELECT ss.year, ss.stress_score, ss.risk_level, ss.raw_score
        FROM   stress_scores ss
        JOIN   countries c ON ss.country_id = c.id
        WHERE  UPPER(c.iso3) = UPPER(?)
        ORDER  BY ss.year ASC
        """,
        (iso3,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_global_trend(db: sqlite3.Connection) -> list[dict]:
    """
    Return the average global stress score per year across all countries.
    Used by the Trends page for the global average line chart.
    """
    rows = db.execute(
        """
        SELECT  ss.year,
                ROUND(AVG(ss.stress_score), 4) AS avg_stress_score,
                COUNT(DISTINCT ss.country_id)  AS country_count
        FROM    stress_scores ss
        JOIN    countries c ON ss.country_id = c.id
        WHERE   c.name IS NOT NULL
          AND   LOWER(c.name) != 'nan'
        GROUP   BY ss.year
        ORDER   BY ss.year ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_indicator_trend(
    db: sqlite3.Connection,
    indicator_code: str,
    iso3_list: Optional[list[str]] = None,
) -> list[dict]:
    """
    Return annual average values of one indicator across all (or selected) countries.
    Used by the Trends page for the indicator deep-dive chart.
    """
    if iso3_list:
        placeholders = ",".join("?" * len(iso3_list))
        sql = f"""
            SELECT ed.year,
                   ROUND(AVG(ed.value), 4) AS avg_value,
                   COUNT(DISTINCT c.id)    AS country_count
            FROM   economic_data ed
            JOIN   indicators i ON ed.indicator_id = i.id
            JOIN   countries  c ON ed.country_id   = c.id
            WHERE  UPPER(i.code) = UPPER(?)
              AND  UPPER(c.iso3) IN ({placeholders})
            GROUP  BY ed.year
            ORDER  BY ed.year ASC
        """
        params = [indicator_code] + [iso3.upper() for iso3 in iso3_list]
    else:
        sql = """
            SELECT ed.year,
                   ROUND(AVG(ed.value), 4) AS avg_value,
                   COUNT(DISTINCT c.id)    AS country_count
            FROM   economic_data ed
            JOIN   indicators i ON ed.indicator_id = i.id
            JOIN   countries  c ON ed.country_id   = c.id
            WHERE  UPPER(i.code) = UPPER(?)
              AND  c.name IS NOT NULL
              AND  LOWER(c.name) != 'nan'
            GROUP  BY ed.year
            ORDER  BY ed.year ASC
        """
        params = [indicator_code]
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
