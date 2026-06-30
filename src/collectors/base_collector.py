"""
src/collectors/base_collector.py
=================================
Abstract base class for all data collectors.

Every collector (WorldBank, IMF, FRED) inherits from BaseCollector and gets:
  - A shared requests.Session with automatic retry on network errors
  - A save_csv() method that writes a consistent CSV to data/raw/
  - A run() template method that orchestrates collect → validate → save
  - A shared logger

Child classes only need to implement collect() → pd.DataFrame.
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class BaseCollector(ABC):
    """
    Abstract base class shared by all data source collectors.

    Subclasses MUST implement:
        collect(self) -> pd.DataFrame
    """

    source_name: str = "base"  # overridden in each subclass

    def __init__(self, raw_data_dir: Path, timeout: int = 30, max_retries: int = 3) -> None:
        self.raw_data_dir = raw_data_dir
        self.timeout = timeout
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)

        # Simple logger — one per collector, writes to root "platform" logger
        self.logger = logging.getLogger(f"platform.{self.source_name}")

        # HTTP session with retry-on-failure adapter
        self.session = self._build_session(max_retries)

    # ------------------------------------------------------------------
    # Session setup
    # ------------------------------------------------------------------

    def _build_session(self, max_retries: int) -> requests.Session:
        """
        Create an HTTP session that automatically retries on:
          - Connection errors
          - Server errors: 429, 500, 502, 503, 504
        Uses exponential backoff: waits 2s, 4s, 8s between retries.
        """
        session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://",  HTTPAdapter(max_retries=retry))
        return session

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict = None) -> requests.Response:
        """Make a GET request, log it, and raise on HTTP errors."""
        self.logger.debug("GET %s | params=%s", url, params)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response

    def save_csv(self, df: pd.DataFrame, filename: str) -> Path:
        """
        Save a DataFrame to data/raw/<filename>.csv.
        Adds an 'ingested_at' column (UTC timestamp) for traceability.
        Overwrites the file on each run (fresh snapshot model).
        """
        if not filename.endswith(".csv"):
            filename += ".csv"

        output_path = self.raw_data_dir / filename
        df = df.copy()
        df["ingested_at"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        df.to_csv(output_path, index=False, encoding="utf-8")

        self.logger.info("Saved %d rows → %s", len(df), output_path.name)
        return output_path

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def collect(self) -> pd.DataFrame:
        """
        Connect to the data source and return a pandas DataFrame.
        Null rows should be filtered before returning.
        """
        ...

    # ------------------------------------------------------------------
    # Template method — orchestrates the full ingestion cycle
    # ------------------------------------------------------------------

    def run(self) -> Path | None:
        """
        Run the full ingestion cycle:
          1. Call collect() to fetch data
          2. Check the result is non-empty
          3. Save to CSV via save_csv()
          4. Return the saved file path (or None on failure)
        """
        self.logger.info("--- Starting: %s ---", self.source_name)

        try:
            df = self.collect()
        except Exception as exc:
            self.logger.error("%s collection failed: %s", self.source_name, exc, exc_info=True)
            return None

        if df is None or df.empty:
            self.logger.warning("%s returned no data — nothing saved.", self.source_name)
            return None

        self.logger.info("%s: collected %d rows, %d columns", self.source_name, len(df), len(df.columns))
        path = self.save_csv(df, filename=f"{self.source_name}_raw")
        self.logger.info("--- Finished: %s ---", self.source_name)
        return path
