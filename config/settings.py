"""
config/settings.py
====================
Single source of truth for all project configuration.

Loads .env via python-dotenv, then exposes typed constants.
Every module imports from here — no os.getenv() calls scattered in the code.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load the .env file from the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)

# ── API Keys ──────────────────────────────────────────────────────────────────
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")

# ── Directories (created automatically at import time) ────────────────────────
DATA_RAW_DIR:       Path = _PROJECT_ROOT / os.getenv("DATA_RAW_DIR",       "data/raw")
DATA_PROCESSED_DIR: Path = _PROJECT_ROOT / os.getenv("DATA_PROCESSED_DIR", "data/processed")
LOGS_DIR:           Path = _PROJECT_ROOT / os.getenv("LOGS_DIR",           "logs")

DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────────
# SQLite database file lives inside data/
DATABASE_PATH: Path = _PROJECT_ROOT / "data" / "economic_stress.db"
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Fitted model parameters — written by the stress engine, reloaded on every run.
# Delete this file to force a full re-fit on the next ETL run.
STRESS_MODEL_PARAMS_PATH: Path = _PROJECT_ROOT / "data" / "stress_model_params.json"

# ── Unified CSV (output of transformer, input to loader) ──────────────────────
UNIFIED_CSV_PATH: Path = DATA_PROCESSED_DIR / "unified_economic_data.csv"

# ── HTTP settings ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES:     int = int(os.getenv("MAX_RETRIES", "3"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# =============================================================================
# World Bank
# =============================================================================
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"

# Indicator catalogue: https://data.worldbank.org/indicator
# Format: { "API_CODE": "canonical_indicator_code" }
WORLD_BANK_INDICATORS = {
    "NY.GDP.MKTP.CD":     "GDP_USD",
    "FP.CPI.TOTL.ZG":    "INFLATION_PCT",
    "SL.UEM.TOTL.ZS":    "UNEMPLOYMENT_PCT",
    "GC.DOD.TOTL.GD.ZS": "GOVT_DEBT_PCT_GDP",
    "BN.CAB.XOKA.GD.ZS": "CURRENT_ACCOUNT_PCT_GDP",
    "FR.INR.LEND":       "INTEREST_RATE_PCT",
}

# ISO-3166 alpha-2 codes joined by semicolons (World Bank uses alpha-2 in query)
WORLD_BANK_COUNTRIES = "all"

WORLD_BANK_START_YEAR = 2000
WORLD_BANK_END_YEAR   = 2023

# =============================================================================
# IMF
# =============================================================================
IMF_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"

# WEO indicator codes: https://www.imf.org/external/datamapper/
# Format: { "WEO_CODE": "canonical_indicator_code" }
IMF_INDICATORS = {
    "NGDP_RPCH":   "GDP_GROWTH_PCT",
    "PCPIPCH":     "INFLATION_PCT",
    "LUR":         "UNEMPLOYMENT_PCT",
    "GGXWDG_NGDP": "GOVT_DEBT_PCT_GDP",
    "BCA_NGDPD":   "CURRENT_ACCOUNT_PCT_GDP",
}

# =============================================================================
# FRED (Federal Reserve Economic Data)
# =============================================================================
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Series catalogue: https://fred.stlouisfed.org/
# Format: { "FRED_SERIES_ID": "canonical_indicator_code" }
FRED_SERIES = {
    "UNRATE":   "UNEMPLOYMENT_PCT",
    "CPIAUCSL": "CPI_INDEX",
    "GDP":      "GDP_USD",
    "FEDFUNDS": "INTEREST_RATE_PCT",
    "T10YIE":   "INFLATION_EXPECTATIONS_PCT",
    "DEXUSEU":  "USD_EUR_FX",
    "VIXCLS":   "VIX_INDEX",
}

FRED_START_DATE = "2000-01-01"
FRED_END_DATE   = "2024-01-01"

# =============================================================================
# Indicator catalogue — maps canonical codes → human labels
# This is the SINGLE source of truth for indicator labels across all sources.
# =============================================================================
INDICATOR_LABELS: dict[str, str] = {
    "GDP_USD":                   "GDP (Current USD)",
    "GDP_GROWTH_PCT":            "Real GDP Growth (%)",
    "INFLATION_PCT":             "Inflation Rate (%)",
    "CPI_INDEX":                 "Consumer Price Index",
    "UNEMPLOYMENT_PCT":          "Unemployment Rate (%)",
    "GOVT_DEBT_PCT_GDP":         "Government Debt (% of GDP)",
    "CURRENT_ACCOUNT_PCT_GDP":   "Current Account Balance (% of GDP)",
    "INTEREST_RATE_PCT":         "Interest Rate (%)",
    "INFLATION_EXPECTATIONS_PCT":"Inflation Expectations (%)",
    "USD_EUR_FX":                "USD/EUR Exchange Rate",
    "VIX_INDEX":                 "CBOE VIX Volatility Index",
}

# =============================================================================
# Stress Score Engine (Phase 4)
# =============================================================================

# Indicators required to compute a stress score.
# A country-year record is skipped if ANY of these is missing.
STRESS_INDICATORS: list[str] = [
    "GDP_GROWTH_PCT",
    "INFLATION_PCT",
    "UNEMPLOYMENT_PCT",
    "INTEREST_RATE_PCT",
    "GOVT_DEBT_PCT_GDP",
]

# Formula weights — must sum to |positive weights| - |negative weights| ≠ 0.
# Positive weight  → higher value means MORE stress
# Negative weight  → higher value means LESS stress (GDP growth)
#
#  raw_score = 0.35×INFLATION + 0.25×UNEMPLOYMENT + 0.20×GOVT_DEBT
#            + 0.15×INTEREST_RATE − 0.15×GDP_GROWTH
STRESS_WEIGHTS: dict[str, float] = {
    "INFLATION_PCT":    +0.35,
    "UNEMPLOYMENT_PCT": +0.25,
    "GOVT_DEBT_PCT_GDP":+0.20,
    "INTEREST_RATE_PCT":+0.15,
    "GDP_GROWTH_PCT":   -0.15,
}

# Risk classification thresholds (applied to the 0-100 normalised score)
RISK_LOW_MAX:    float = 30.0   # 0  – 30  → Low Risk
RISK_MEDIUM_MAX: float = 60.0   # 31 – 60  → Medium Risk
                                 # 61 – 100 → High Risk

