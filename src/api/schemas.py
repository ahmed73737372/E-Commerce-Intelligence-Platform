"""
src/api/schemas.py
===================

Pydantic response models for all API endpoints.

RULES
-----
- Every route handler returns a typed Pydantic model (never a raw dict)
- Optional fields use None defaults (e.g. stress_score when no data exists)
- All models use model_config = ConfigDict(from_attributes=True) so they
  can be constructed from sqlite3.Row objects directly

MODEL HIERARCHY
---------------
  PlatformStatus          ← GET /
  CountryBase             ← GET /countries (list item)
  IndicatorValue          ← nested inside CountryDetail
  CountryDetail           ← GET /country/{iso3}
  StressEntry             ← GET /top-risk, /top-safe, /stress-map (list item)
  GlobalSummary           ← GET /global-summary
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PlatformStatus(BaseModel):
    """Root health-check response."""
    project: str
    status:  str


class CountryBase(BaseModel):
    """Minimal country representation — used in list endpoints."""
    model_config = ConfigDict(from_attributes=True)

    iso3: str = Field(..., description="ISO 3166-1 alpha-3 country code")
    name: str = Field(..., description="Full country name")


class IndicatorValue(BaseModel):
    """One economic indicator value for a country (latest available year)."""
    model_config = ConfigDict(from_attributes=True)

    code:  str   = Field(..., description="Canonical indicator code")
    label: str   = Field(..., description="Human-readable label")
    year:  int   = Field(..., description="Data year")
    value: float = Field(..., description="Indicator value")


class CountryDetail(BaseModel):
    """
    Full country profile — returned by GET /country/{iso3}.
    stress_score and risk_level are None when no scores have been calculated yet.
    """
    model_config = ConfigDict(from_attributes=True)

    iso3:         str                    = Field(...)
    country_name: str                    = Field(...)
    latest_year:  Optional[int]          = Field(None, description="Latest year for which a stress score exists")
    stress_score: Optional[float]        = Field(None, description="Min-Max normalised stress score (0–100)")
    risk_level:   Optional[str]          = Field(None, description="Low Risk | Medium Risk | High Risk")
    indicators:   list[IndicatorValue]   = Field(default_factory=list)


class StressEntry(BaseModel):
    """One country's latest stress score — used in ranking and map endpoints."""
    model_config = ConfigDict(from_attributes=True)

    iso3:         str           = Field(...)
    country_name: str           = Field(...)
    year:         Optional[int] = Field(None, description="Score year")
    stress_score: float         = Field(..., description="0–100 normalised score")
    risk_level:   str           = Field(..., description="Low Risk | Medium Risk | High Risk")


class GlobalSummary(BaseModel):
    """Aggregate statistics across all countries with stress scores."""
    model_config = ConfigDict(from_attributes=True)

    total_countries:      int   = Field(..., description="Countries with at least one stress score")
    average_stress_score: float = Field(..., description="Mean stress score across all countries (latest year)")
    high_risk_countries:  int   = Field(..., description="Countries classified as High Risk")
    medium_risk_countries: int  = Field(..., description="Countries classified as Medium Risk")
    low_risk_countries:   int   = Field(..., description="Countries classified as Low Risk")
