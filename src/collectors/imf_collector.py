"""
src/collectors/imf_collector.py
=================================
Fetches World Economic Outlook (WEO) data from the IMF DataMapper API.

API: https://www.imf.org/external/datamapper/api/v1
No authentication required.

Endpoint used:
  GET /{weo_code}

Response structure:
  {
    "values": {
      "NGDP_RPCH": {
        "USA": {"2000": 4.1, "2001": 1.0, ...},
        "CHN": {"2000": 8.4, ...},
        ...
      }
    }
  }

One request fetches ALL countries and ALL years for a given indicator.
No pagination needed.

Output contract — exactly 7 columns (matches unified schema):
  country_iso3 | country_name | indicator_code | indicator_label | value | year | source

Note: IMF returns country data by ISO2 code (e.g. "US") but also includes
      ISO3 codes in some endpoints. We store whatever key the API returns
      in country_iso3 — the transformer will resolve country_name.
"""

import time

import pandas as pd

import config.settings as cfg
from src.collectors.base_collector import BaseCollector


class IMFCollector(BaseCollector):
    """Collects IMF World Economic Outlook indicators for all available countries."""

    source_name = "imf"

    def __init__(self) -> None:
        super().__init__(
            raw_data_dir=cfg.DATA_RAW_DIR,
            timeout=cfg.REQUEST_TIMEOUT,
            max_retries=cfg.MAX_RETRIES,
        )
        self.base_url         = cfg.IMF_BASE_URL
        # {"NGDP_RPCH": "GDP_GROWTH_PCT", ...}  weo_code → canonical_code
        self.indicators       = cfg.IMF_INDICATORS
        # {"GDP_GROWTH_PCT": "Real GDP Growth (%)", ...}
        self.indicator_labels = cfg.INDICATOR_LABELS

    # ------------------------------------------------------------------
    # collect() — required by BaseCollector
    # ------------------------------------------------------------------

    def collect(self) -> pd.DataFrame:
        """
        Fetch each configured IMF indicator and return a combined DataFrame.
        Each indicator request returns data for ~190 countries × ~40 years.
        """
        frames = []
        total = len(self.indicators)

        self.logger.info("Fetching %d IMF WEO indicators.", total)

        for i, (weo_code, canonical_code) in enumerate(self.indicators.items(), start=1):
            human_label = self.indicator_labels.get(canonical_code, canonical_code)
            self.logger.info("[%d/%d] %s (%s)", i, total, canonical_code, weo_code)
            try:
                df = self._fetch_indicator(weo_code, canonical_code, human_label)
                if not df.empty:
                    frames.append(df)
                    self.logger.info("  OK: %d records", len(df))
                else:
                    self.logger.warning("  No data returned for %s", weo_code)
            except Exception as exc:
                self.logger.error("  Failed %s: %s", weo_code, exc)
            time.sleep(1.0)  # IMF API is sensitive to rapid requests

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        self.logger.info("IMF total: %d records", len(result))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_indicator(self, weo_code: str, canonical_code: str, human_label: str) -> pd.DataFrame:
        """
        Fetch one IMF indicator for all countries and all years.

        Parameters
        ----------
        weo_code       : str  IMF WEO code, e.g. "NGDP_RPCH" — used in URL only
        canonical_code : str  Standardized code, e.g. "GDP_GROWTH_PCT" — stored in output
        human_label    : str  Human-readable label — stored in output
        """
        url = f"{self.base_url}/{weo_code}"
        payload = self._get(url).json()

        # Navigate: values → weo_code → {country: {year: value}}
        country_data = payload.get("values", {}).get(weo_code, {})
        if not country_data:
            self.logger.warning("Empty data for IMF indicator %s", weo_code)
            return pd.DataFrame()

        return self._to_dataframe(country_data, canonical_code, human_label)

    def _to_dataframe(self, country_data: dict, canonical_code: str, human_label: str) -> pd.DataFrame:
        """
        Flatten the nested { country_code: { year: value } } structure into rows.

        Output columns:
            country_iso3, country_name, indicator_code, indicator_label, value, year, source

        Note: IMF uses its own country codes (often ISO2 or ISO3).
              country_name is left blank here — the transformer fills it
              from the ISO3_TO_NAME mapping.
        """
        rows = []
        for country_code, year_values in country_data.items():
            if not isinstance(year_values, dict):
                continue
            for year_str, raw_value in year_values.items():
                if raw_value is None:
                    continue
                try:
                    rows.append({
                        "country_iso3":   country_code.strip(),
                        "country_name":   "",      # resolved in transformer
                        "indicator_code": canonical_code,
                        "indicator_label": human_label,
                        "year":           int(year_str),
                        "value":          float(raw_value),
                        "source":         "IMF",
                    })
                except (ValueError, TypeError):
                    continue
        return pd.DataFrame(rows)
