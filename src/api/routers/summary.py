"""
src/api/routers/summary.py
===========================

Routes:
  GET /global-summary   → aggregate statistics across all countries
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from src.api.database import get_db
from src.api.schemas  import GlobalSummary
from src.api          import services

router = APIRouter(tags=["Summary"])


@router.get(
    "/global-summary",
    response_model=GlobalSummary,
    summary="Global economic stress statistics",
    description=(
        "Returns aggregate statistics across all countries with stress scores: "
        "total country count, average score, and breakdown by risk level. "
        "All figures use the latest available stress score per country."
    ),
)
def global_summary(db: sqlite3.Connection = Depends(get_db)) -> GlobalSummary:
    """Return global aggregate stress statistics."""
    data = services.get_global_summary(db)

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="No stress scores found. Run the ETL pipeline first.",
        )

    return GlobalSummary(**data)
