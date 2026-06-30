"""
src/api/routers/stress.py
==========================

Routes:
  GET /top-risk     → top 10 highest stress score countries
  GET /top-safe     → top 10 lowest stress score countries
  GET /stress-map   → all countries with latest stress score (for dashboard)
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.database import get_db
from src.api.schemas  import StressEntry
from src.api          import services

router = APIRouter(tags=["Stress Scores"])


@router.get(
    "/top-risk",
    response_model=list[StressEntry],
    summary="Top 10 highest-stress countries",
    description=(
        "Returns up to 10 countries with the highest economic stress scores "
        "(latest year per country). High stress = potential economic instability."
    ),
)
def top_risk(
    limit: int = Query(default=10, ge=1, le=50, description="Number of countries to return"),
    db: sqlite3.Connection = Depends(get_db),
) -> list[StressEntry]:
    """Return countries ranked by highest (worst) stress score."""
    rows = services.get_top_risk(db, limit=limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No stress scores found. Run the ETL pipeline first.",
        )
    return [StressEntry(**r) for r in rows]


@router.get(
    "/top-safe",
    response_model=list[StressEntry],
    summary="Top 10 lowest-stress countries",
    description=(
        "Returns up to 10 countries with the lowest economic stress scores "
        "(latest year per country). Low stress = relatively stable economies."
    ),
)
def top_safe(
    limit: int = Query(default=10, ge=1, le=50, description="Number of countries to return"),
    db: sqlite3.Connection = Depends(get_db),
) -> list[StressEntry]:
    """Return countries ranked by lowest (best) stress score."""
    rows = services.get_top_safe(db, limit=limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No stress scores found. Run the ETL pipeline first.",
        )
    return [StressEntry(**r) for r in rows]


@router.get(
    "/stress-map",
    response_model=list[StressEntry],
    summary="Stress scores for all countries (map data)",
    description=(
        "Returns the latest stress score and risk classification for every "
        "country that has been scored. Ordered alphabetically. "
        "Intended as the data feed for a future choropleth map dashboard."
    ),
)
def stress_map(db: sqlite3.Connection = Depends(get_db)) -> list[StressEntry]:
    """Return latest stress score for all scored countries."""
    rows = services.get_stress_map(db)
    return [StressEntry(**r) for r in rows]
