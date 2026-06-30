"""
src/collectors/world_bank_collector.py
=======================================
Fetches macroeconomic data from the World Bank Open Data API.

API: https://api.worldbank.org/v2
No authentication required.

Endpoint used:
  GET /v2/country/{countries}/indicator/{indicator_code}?format=json&per_page=1000&date=2000:2023

The response is a 2-element list:
  [0] → metadata (total pages, total records)
  [1] → list of data-point objects

Output contract — exactly 7 columns (matches unified schema):
  country_iso3 | country_name | indicator_code | indicator_label | value | year | source

Pagination: if the API returns multiple pages, each page is fetched
and its records are appended.

"""

import time

import pandas as pd

import config.settings as cfg
from src.collectors.base_collector import BaseCollector


class WorldBankCollector(BaseCollector):
    """Collects World Bank macroeconomic indicators for a set of countries."""

    source_name = "world_bank"

    def __init__(self) -> None:
        super().__init__(
            raw_data_dir=cfg.DATA_RAW_DIR,
            timeout=cfg.REQUEST_TIMEOUT,
            max_retries=cfg.MAX_RETRIES,
        )
        self.base_url        = cfg.WORLD_BANK_BASE_URL
        # {"NY.GDP.MKTP.CD": "GDP_USD", ...}  api_code → canonical_code
        self.indicators      = cfg.WORLD_BANK_INDICATORS
        # {"GDP_USD": "GDP (Current USD)", ...}  canonical_code → human label
        self.indicator_labels = cfg.INDICATOR_LABELS
        self.countries        = cfg.WORLD_BANK_COUNTRIES
        self.start_year       = cfg.WORLD_BANK_START_YEAR
        self.end_year         = cfg.WORLD_BANK_END_YEAR

    # ------------------------------------------------------------------
    # collect() — required by BaseCollector
    # ------------------------------------------------------------------

    def collect(self) -> pd.DataFrame:
        """
        Iterate over each configured indicator, fetch data for all countries,
        and return a combined DataFrame.
        """
        frames = []
        total = len(self.indicators)

        self.logger.info("Fetching %d World Bank indicators for: %s", total, self.countries)

        for i, (api_code, canonical_code) in enumerate(self.indicators.items(), start=1):
            human_label = self.indicator_labels.get(canonical_code, canonical_code)
            self.logger.info("[%d/%d] %s (%s)", i, total, canonical_code, api_code)
            try:
                df = self._fetch_indicator(api_code, canonical_code, human_label)
                if not df.empty:
                    frames.append(df)
                    self.logger.info("  OK: %d records", len(df))
                else:
                    self.logger.warning("  No data returned for %s", code)
            except Exception as exc:
                self.logger.error("  Failed %s: %s", code, exc)
            time.sleep(0.5)  # be polite to the API

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        self.logger.info("World Bank total: %d records", len(result))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_indicator(self, api_code: str, canonical_code: str, human_label: str) -> pd.DataFrame:
        """
        Fetch all pages for one indicator across all configured countries.

        Parameters
        ----------
        api_code       : str  World Bank API code, e.g. "NY.GDP.MKTP.CD" — used in URL only
        canonical_code : str  Standardized code, e.g. "GDP_USD" — stored in output
        human_label    : str  Human-readable label, e.g. "GDP (Current USD)" — stored in output
        """
        url = f"{self.base_url}/country/{self.countries}/indicator/{api_code}"
        params = {
            "format":   "json",
            "per_page": 1000,
            "date":     f"{self.start_year}:{self.end_year}",
        }

        # First page
        payload = self._get(url, params).json()
        if not isinstance(payload, list) or len(payload) < 2:
            self.logger.warning("Unexpected response for %s", api_code)
            return pd.DataFrame()

        metadata = payload[0]
        records  = payload[1] or []

        # Remaining pages
        total_pages = int(metadata.get("pages", 1))
        for page in range(2, total_pages + 1):
            params["page"] = page
            extra = self._get(url, params).json()
            if isinstance(extra, list) and len(extra) == 2 and extra[1]:
                records.extend(extra[1])
            time.sleep(0.2)

        return self._to_dataframe(records, canonical_code, human_label)

    def _to_dataframe(self, records: list, canonical_code: str, label: str) -> pd.DataFrame:
        """
        Convert raw API records to a DataFrame using the strict 7-column contract.
        Rows where 'value' is None are dropped (API returns placeholders for missing years).

        Output columns:
            country_iso3, country_name, indicator_code, indicator_label, value, year, source
        """
        rows = []
        for rec in records:
            val = rec.get("value")
            if val is None:
                continue
            rows.append({
                "country_iso3":    rec.get("countryiso3code", "").strip(),
                "country_name":    rec.get("country", {}).get("value", "").strip(),
                "indicator_code":  canonical_code,          # e.g. GDP_USD
                "indicator_label": label,                   # e.g. GDP (Current USD)
                "year":            int(rec.get("date", 0)),
                "value":           float(val),
                "source":          "World Bank",
            })
        return pd.DataFrame(rows)
