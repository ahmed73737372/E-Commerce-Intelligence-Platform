"""Collectors sub-package — exposes all three collector classes."""

from src.collectors.world_bank_collector import WorldBankCollector
from src.collectors.imf_collector import IMFCollector
from src.collectors.fred_collector import FREDCollector

__all__ = ["WorldBankCollector", "IMFCollector", "FREDCollector"]
