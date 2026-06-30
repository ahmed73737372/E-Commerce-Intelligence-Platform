"""
src/api/routers/countries.py
==============================

Routes:
  GET /countries        → list of all countries
  GET /country/{iso3}   → full profile for one country
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from src.api.database import get_db
from src.api.schemas  import CountryBase, CountryDetail, IndicatorValue
from src.api          import services

router = APIRouter(tags=["Countries"])


@router.get(
    "/countries",
    response_model=list[CountryBase],
    summary="List all countries",
    description="Returns every country present in the database, ordered alphabetically.",
)
def list_countries(db: sqlite3.Connection = Depends(get_db)) -> list[CountryBase]:
    """Return all countries ordered by name."""
    rows = services.get_all_countries(db)
    return [CountryBase(**r) for r in rows]


@router.get(
    "/country/{iso3}",
    response_model=CountryDetail,
    summary="Country detail profile",
    description=(
        "Returns full country profile including the latest stress score, "
        "risk classification, and latest available value for every economic indicator. "
        "Returns HTTP 404 if the ISO3 code is not found."
    ),
)
def country_detail(
    iso3: str,
    db: sqlite3.Connection = Depends(get_db),
) -> CountryDetail:
    """Return full country profile for a given ISO3 code."""
    data = services.get_country_detail(db, iso3.upper())

    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{iso3.upper()}' not found. "
                   "Use GET /countries to see all valid ISO3 codes.",
        )

    # Build nested IndicatorValue list
    indicators = [IndicatorValue(**ind) for ind in data.get("indicators", [])]

    return CountryDetail(
        iso3         = data["iso3"],
        country_name = data["country_name"],
        latest_year  = data["latest_year"],
        stress_score = data["stress_score"],
        risk_level   = data["risk_level"],
        indicators   = indicators,
    )
