"""
src/api/routers/trends.py
==========================

Routes:
  GET /country/{iso3}/history   -> all historical stress scores for a country
  GET /global-trend             -> global average stress score per year
  GET /indicator-trend/{code}   -> global average value of one indicator per year
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.database import get_db
from src.api          import services

router = APIRouter(tags=["Trends"])


@router.get(
    "/country/{iso3}/history",
    summary="Country historical stress scores",
)
def country_history(
    iso3: str,
    db: sqlite3.Connection = Depends(get_db),
) -> list:
    country = services.get_country_by_iso3(db, iso3.upper())
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{iso3.upper()}' not found.")
    return services.get_country_history(db, iso3.upper())


@router.get(
    "/global-trend",
    summary="Global average stress score per year",
)
def global_trend(
    db: sqlite3.Connection = Depends(get_db),
) -> list:
    return services.get_global_trend(db)


@router.get(
    "/indicator-trend/{code}",
    summary="Indicator global trend",
)
def indicator_trend(
    code: str,
    iso3: Optional[str] = Query(default=None),
    db: sqlite3.Connection = Depends(get_db),
) -> list:
    iso3_list = [x.strip().upper() for x in iso3.split(",")] if iso3 else None
    data = services.get_indicator_trend(db, code.upper(), iso3_list)
    if not data:
        raise HTTPException(status_code=404, detail=f"No data for indicator '{code.upper()}'.")
    return data
