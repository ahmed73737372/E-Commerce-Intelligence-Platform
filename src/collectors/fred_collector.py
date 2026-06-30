"""
src/collectors/fred_collector.py
==================================
Fetches economic time-series from the FRED API (Federal Reserve, St. Louis).

API: https://api.stlouisfed.org/fred
Requires a free API key → register at https://fred.stlouisfed.org/

Endpoint used:
  GET /series/observations
  Parameters: series_id, api_key, file_type=json,
              observation_start, observation_end

Response:
  {
    "observations": [
      {"date": "2000-01-01", "value": "4.0"},
      ...
    ]
  }

Note: FRED uses the string "." to indicate a missing value — filtered out.

FRED is US-only data, so:
  country_iso3  = "USA"  (hardcoded)
  country_name  = "United States"  (hardcoded)

Output contract — exactly 7 columns (matches unified schema):
  country_iso3 | country_name | indicator_code | indicator_label | value | year | source
"""

import time

import pandas as pd

import config.settings as cfg
from src.collectors.base_collector import BaseCollector

# FRED is US-only
_FRED_COUNTRY_ISO3 = "USA"
_FRED_COUNTRY_NAME = "United States"


class FREDCollector(BaseCollector):
    """
    Collects US economic time-series from the FRED REST API.
    Requires FRED_API_KEY to be set in .env.
    """

    source_name = "fred"

    def __init__(self) -> None:
        super().__init__(
            raw_data_dir=cfg.DATA_RAW_DIR,
            timeout=cfg.REQUEST_TIMEOUT,
            max_retries=cfg.MAX_RETRIES,
        )
        self.base_url         = cfg.FRED_BASE_URL
        self.api_key          = cfg.FRED_API_KEY
        # {"UNRATE": "UNEMPLOYMENT_PCT", ...}  fred_series_id → canonical_code
        self.series           = cfg.FRED_SERIES
        # {"UNEMPLOYMENT_PCT": "Unemployment Rate (%)", ...}
        self.indicator_labels = cfg.INDICATOR_LABELS
        self.start_date       = cfg.FRED_START_DATE
        self.end_date         = cfg.FRED_END_DATE

        if not self.api_key or self.api_key == "your_fred_api_key_here":
            self.logger.warning(
                "FRED_API_KEY not set. "
                "Get a free key at https://fred.stlouisfed.org/ and add it to .env"
            )

    # ------------------------------------------------------------------
    # collect() — required by BaseCollector
    # ------------------------------------------------------------------

    def collect(self) -> pd.DataFrame:
        """
        Fetch each configured FRED series and return a combined DataFrame.
        Returns empty DataFrame if no valid API key is configured.
        """
        if not self.api_key or self.api_key == "your_fred_api_key_here":
            self.logger.error("Skipping FRED — no valid API key.")
            return pd.DataFrame()

        frames = []
        total = len(self.series)

        self.logger.info("Fetching %d FRED series.", total)

        for i, (series_id, canonical_code) in enumerate(self.series.items(), start=1):
            human_label = self.indicator_labels.get(canonical_code, canonical_code)
            self.logger.info("[%d/%d] %s (%s)", i, total, canonical_code, series_id)
            try:
                df = self._fetch_series(series_id, canonical_code, human_label)
                if not df.empty:
                    frames.append(df)
                    self.logger.info("  OK: %d observations", len(df))
                else:
                    self.logger.warning("  No data returned for %s", series_id)
            except Exception as exc:
                self.logger.error("  Failed %s: %s", series_id, exc)
            time.sleep(0.6)  # FRED rate limit: 120 requests/minute

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        self.logger.info("FRED total: %d observations", len(result))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_series(self, series_id: str, canonical_code: str, human_label: str) -> pd.DataFrame:
        """
        Fetch all observations for one FRED series in the configured date range.

        Parameters
        ----------
        series_id      : str  FRED series identifier, e.g. "UNRATE" — used in request only
        canonical_code : str  Standardized code, e.g. "UNEMPLOYMENT_PCT" — stored in output
        human_label    : str  Human-readable label — stored in output
        """
        url = f"{self.base_url}/series/observations"
        params = {
            "series_id":         series_id,
            "api_key":           self.api_key,
            "file_type":         "json",
            "observation_start": self.start_date,
            "observation_end":   self.end_date,
            "sort_order":        "asc",
        }

        payload = self._get(url, params).json()
        observations = payload.get("observations", [])

        if not observations:
            return pd.DataFrame()

        return self._to_dataframe(observations, canonical_code, human_label)

    def _to_dataframe(self, observations: list, canonical_code: str, human_label: str) -> pd.DataFrame:
        """
        Convert raw FRED observation list to a DataFrame.

        - Filters out rows where value == "." (FRED missing-data sentinel)
        - Extracts year from the date string
        - Hardcodes country_iso3 = "USA" and country_name = "United States"

        Output columns:
            country_iso3, country_name, indicator_code, indicator_label, value, year, source
        """
        rows = []
        for obs in observations:
            raw = obs.get("value", ".")
            if raw == ".":
                continue
            try:
                rows.append({
                    "country_iso3":    _FRED_COUNTRY_ISO3,
                    "country_name":    _FRED_COUNTRY_NAME,
                    "indicator_code":  canonical_code,
                    "indicator_label": human_label,
                    "year":            int(obs.get("date", "0000")[:4]),
                    "value":           float(raw),
                    "source":          "FRED",
                })
            except (ValueError, TypeError):
                continue

        return pd.DataFrame(rows)
