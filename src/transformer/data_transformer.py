"""
src/transformer/data_transformer.py
=====================================

PURPOSE
-------
This is the BRIDGE between Phase 1 (raw CSVs) and Phase 2 (SQLite database).
It enforces a strict unified schema that every row from every source must
conform to before it can be loaded into the database.

UNIFIED DATA CONTRACT
---------------------
Every row output by this module has EXACTLY these 7 columns:

    Column          Type   Example                  Description
    --------------- -----  -----------------------  -----------------------------------
    country_iso3    str    "USA"                    ISO-3166 alpha-3 country code
    country_name    str    "United States"          Full English country name
    indicator_code  str    "GDP_USD"                Canonical indicator code (uppercase)
    indicator_label str    "GDP (Current USD)"      Human-readable label
    year            int    2021                     4-digit calendar year
    value           float  23315.08                 Numeric value for that indicator
    source          str    "World Bank"             Data origin: World Bank / IMF / FRED

WHAT THIS MODULE DOES
---------------------
1. Reads each raw CSV from data/raw/
2. Validates that the required columns are present
3. Fills in country_name where missing (using ISO3_TO_NAME mapping)
4. Drops rows with null values or years before 1990
5. Concatenates all sources into a single unified DataFrame
6. Saves it to data/processed/unified_economic_data.csv

WHAT THIS MODULE DOES NOT DO
-----------------------------
- Does not call any API
- Does not write to the database (that is loader.py's job)
- Does not duplicate any logic from the collectors
"""

import logging
import pandas as pd

import config.settings as cfg

logger = logging.getLogger("platform.transformer")

# ── The 7-column unified contract ──────────────────────────────────────────────
UNIFIED_COLUMNS = [
    "country_iso3",
    "country_name",
    "indicator_code",
    "indicator_label",
    "year",
    "value",
    "source",
]

# ── ISO-3166 alpha-3 → English country name ───────────────────────────────────
# This is the authoritative country name mapping for the entire project.
# Used to fill country_name when a collector (e.g. IMF) leaves it blank.
ISO3_TO_NAME: dict[str, str] = {
    "AFG": "Afghanistan",       "ALB": "Albania",
    "DZA": "Algeria",           "ARG": "Argentina",
    "ARM": "Armenia",           "AUS": "Australia",
    "AUT": "Austria",           "AZE": "Azerbaijan",
    "BHR": "Bahrain",           "BGD": "Bangladesh",
    "BLR": "Belarus",           "BEL": "Belgium",
    "BEN": "Benin",             "BOL": "Bolivia",
    "BIH": "Bosnia",            "BRA": "Brazil",
    "BGR": "Bulgaria",          "CMR": "Cameroon",
    "CAN": "Canada",            "CHL": "Chile",
    "CHN": "China",             "COL": "Colombia",
    "COD": "Congo, D.R.",       "CIV": "Cote d'Ivoire",
    "HRV": "Croatia",           "CZE": "Czech Republic",
    "DNK": "Denmark",           "DOM": "Dominican Republic",
    "ECU": "Ecuador",           "EGY": "Egypt",
    "ETH": "Ethiopia",          "FIN": "Finland",
    "FRA": "France",            "DEU": "Germany",
    "GHA": "Ghana",             "GRC": "Greece",
    "GTM": "Guatemala",         "HUN": "Hungary",
    "IND": "India",             "IDN": "Indonesia",
    "IRN": "Iran",              "IRQ": "Iraq",
    "IRL": "Ireland",           "ISR": "Israel",
    "ITA": "Italy",             "JAM": "Jamaica",
    "JPN": "Japan",             "JOR": "Jordan",
    "KAZ": "Kazakhstan",        "KEN": "Kenya",
    "KOR": "South Korea",       "KWT": "Kuwait",
    "LBN": "Lebanon",           "LBY": "Libya",
    "MYS": "Malaysia",          "MEX": "Mexico",
    "MAR": "Morocco",           "MOZ": "Mozambique",
    "MMR": "Myanmar",           "NLD": "Netherlands",
    "NZL": "New Zealand",       "NGA": "Nigeria",
    "NOR": "Norway",            "OMN": "Oman",
    "PAK": "Pakistan",          "PAN": "Panama",
    "PER": "Peru",              "PHL": "Philippines",
    "POL": "Poland",            "PRT": "Portugal",
    "QAT": "Qatar",             "ROU": "Romania",
    "RUS": "Russia",            "SAU": "Saudi Arabia",
    "SEN": "Senegal",           "ZAF": "South Africa",
    "ESP": "Spain",             "LKA": "Sri Lanka",
    "SDN": "Sudan",             "SWE": "Sweden",
    "CHE": "Switzerland",       "SYR": "Syria",
    "TWN": "Taiwan",            "TZA": "Tanzania",
    "THA": "Thailand",          "TUN": "Tunisia",
    "TUR": "Turkey",            "UGA": "Uganda",
    "UKR": "Ukraine",           "ARE": "United Arab Emirates",
    "GBR": "United Kingdom",    "USA": "United States",
    "URY": "Uruguay",           "UZB": "Uzbekistan",
    "VEN": "Venezuela",         "VNM": "Vietnam",
    "YEM": "Yemen",             "ZMB": "Zambia",
    "ZWE": "Zimbabwe",
    "ABW": "Aruba",             "AGO": "Angola",
    "AND": "Andorra",           "ATG": "Antigua and Barbuda",
    "BDI": "Burundi",           "BRB": "Barbados",
    "BHS": "Bahamas",           "BLZ": "Belize",
    "BTN": "Bhutan",            "BWA": "Botswana",
    "CAF": "Central African Republic", "COG": "Congo, Rep.",
    "COM": "Comoros",           "CPV": "Cabo Verde",
    "DJI": "Djibouti",          "DMA": "Dominica",
    "ERI": "Eritrea",           "FJI": "Fiji",
    "FSM": "Micronesia",        "GAB": "Gabon",
    "GMB": "Gambia",            "GNB": "Guinea-Bissau",
    "GNQ": "Equatorial Guinea", "GRD": "Grenada",
    "GUY": "Guyana",            "HTI": "Haiti",
    "KIR": "Kiribati",          "KNA": "St. Kitts and Nevis",
    "LBR": "Liberia",           "LCA": "St. Lucia",
    "LSO": "Lesotho",           "MAC": "Macao",
    "MDG": "Madagascar",        "MDV": "Maldives",
    "MHL": "Marshall Islands",  "MLI": "Mali",
    "MNE": "Montenegro",        "MRT": "Mauritania",
    "MUS": "Mauritius",         "MWI": "Malawi",
    "NAM": "Namibia",           "NER": "Niger",
    "NIC": "Nicaragua",         "NRU": "Nauru",
    "PLW": "Palau",             "PNG": "Papua New Guinea",
    "RWA": "Rwanda",            "WSM": "Samoa",
    "STP": "Sao Tome and Principe", "SUR": "Suriname",
    "SYC": "Seychelles",        "TCD": "Chad",
    "TGO": "Togo",              "TON": "Tonga",
    "TTO": "Trinidad and Tobago", "TUV": "Tuvalu",
    "VCT": "St. Vincent and the Grenadines", "VUT": "Vanuatu",
    "CYP": "Cyprus",           "EST": "Estonia",
    "GIN": "Guinea",           "LIE": "Liechtenstein",
    "LTU": "Lithuania",        "LUX": "Luxembourg",
    "LVA": "Latvia",           "PRI": "Puerto Rico",
    "SOM": "Somalia",          "SVK": "Slovakia",
    "SVN": "Slovenia",         "TKM": "Turkmenistan",
    "MKD": "North Macedonia",  "MNG": "Mongolia",
    "SGP": "Singapore",        "SLB": "Solomon Islands",
    "SLE": "Sierra Leone",     "SLV": "El Salvador",
    "SRB": "Serbia",           "SSD": "South Sudan",
    "SWZ": "Eswatini",         "TJK": "Tajikistan",
    "TLS": "Timor-Leste",      "NPL": "Nepal",
    "KGZ": "Kyrgyzstan",       "KHM": "Cambodia",
    "LAO": "Lao PDR",          "HND": "Honduras",
    "ISL": "Iceland",          "MLT": "Malta",
    "PRY": "Paraguay",         "SMR": "San Marino",
}


class DataTransformer:
    """
    Converts raw collector CSVs into the 7-column unified data contract.

    The collectors already output all 7 required columns; this class:
      1. Reads each raw CSV and validates columns are present
      2. Fills country_name from ISO3_TO_NAME for any blanks
      3. Drops rows that violate the contract (null values, pre-1990 years)
      4. Merges all sources and saves unified_economic_data.csv

    Usage
    -----
        transformer = DataTransformer()
        unified_df  = transformer.load_and_transform_all()
    """

    def __init__(self) -> None:
        self.raw_dir      = cfg.DATA_RAW_DIR
        self.proc_dir     = cfg.DATA_PROCESSED_DIR
        self.output_path  = cfg.UNIFIED_CSV_PATH
        self.proc_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def load_and_transform_all(self) -> pd.DataFrame:
        """
        Read all raw CSVs, validate and clean each one, merge them into
        a single unified DataFrame, and save it to:
            data/processed/unified_economic_data.csv

        Returns the unified DataFrame (empty if no raw files found).
        """
        source_files = {
            "World Bank": self.raw_dir / "world_bank_raw.csv",
            "IMF":        self.raw_dir / "imf_raw.csv",
            "FRED":       self.raw_dir / "fred_raw.csv",
        }

        frames = []
        for source_label, path in source_files.items():
            if not path.exists():
                logger.warning("%s raw file not found: %s", source_label, path.name)
                continue
            try:
                raw = pd.read_csv(path, low_memory=False)
                cleaned = self._transform(raw, source_label)
                if not cleaned.empty:
                    frames.append(cleaned)
                    logger.info("%-12s → %d rows after cleaning", source_label, len(cleaned))
            except Exception as exc:
                logger.error("Failed to transform %s: %s", source_label, exc, exc_info=True)

        if not frames:
            logger.error("No data to unify. Run main.py first to collect raw data.")
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        unified = (
            pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset=["country_iso3", "indicator_code", "year"])
            .sort_values(["country_iso3", "indicator_code", "year"])
            .reset_index(drop=True)
        )

        # ── 7. Enforce Complete Indicator Sets ──────────────────────────
        # Only keep (country, year) combinations that have all 5 strictly required indicators.
        required_indicators = {
            "GDP_GROWTH_PCT", "INFLATION_PCT", "UNEMPLOYMENT_PCT", 
            "GOVT_DEBT_PCT_GDP", "INTEREST_RATE_PCT"
        }
        
        # Create a boolean mask of rows that have a required indicator
        req_df = unified[unified["indicator_code"].isin(required_indicators)]
        
        # Group by country and year to count how many distinct required indicators they have
        counts = req_df.groupby(["country_iso3", "year"])["indicator_code"].nunique()
        
        # Keep only the (country, year) pairs that have at least 3 distinct required indicators
        valid_pairs = counts[counts >= 3].index
        
        # Filter the unified dataset to only include those valid (country, year) pairs
        # We set an index to efficiently filter, then reset it
        unified = unified.set_index(["country_iso3", "year"])
        unified = unified.loc[unified.index.isin(valid_pairs)].reset_index()
        
        # Reorder to UNIFIED_COLUMNS to be safe
        unified = unified[UNIFIED_COLUMNS]

        unified.to_csv(self.output_path, index=False, encoding="utf-8")
        logger.info(
            "Unified CSV saved: %d rows, %d sources → %s",
            len(unified),
            len(frames),
            self.output_path.name,
        )
        return unified

    # ------------------------------------------------------------------
    # Internal transformation (same logic for all 3 sources)
    # ------------------------------------------------------------------

    def _transform(self, df: pd.DataFrame, source_label: str) -> pd.DataFrame:
        """
        Validate that the raw DataFrame matches the 7-column contract,
        then clean and return only the unified columns.

        Steps:
          1. Verify all 7 required columns exist
          2. Coerce value to float, drop non-numeric rows
          3. Coerce year to int, drop rows where year < 1990
          4. Fill country_name from ISO3_TO_NAME where it is missing/blank
          5. Strip whitespace from string columns
          6. Return only the 7 unified columns, in order
        """
        self._validate_columns(df, source_label)

        # Work on a copy so we never mutate the original
        df = df[UNIFIED_COLUMNS].copy()

        # ── Numeric coercion ───────────────────────────────────────────
        before = len(df)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["year"]  = pd.to_numeric(df["year"],  errors="coerce")
        df = df.dropna(subset=["value", "year"])
        df["year"] = df["year"].astype(int)

        # ── Filter to safe time window (2000-2024) ─────────────────────
        df = df[(df["year"] >= 2000) & (df["year"] <= 2024)]

        dropped = before - len(df)
        if dropped:
            logger.debug("%s: dropped %d rows (null/invalid/pre-1990)", source_label, dropped)

        # ── Fill missing country_name from ISO3 mapping ────────────────
        df["country_name"] = df["country_name"].fillna("").astype(str)
        missing_name = df["country_name"].str.strip() == ""

        if missing_name.any():
            df.loc[missing_name, "country_name"] = (
                df.loc[missing_name, "country_iso3"].map(ISO3_TO_NAME)
            )

        # ── Strip whitespace from all string columns ───────────────────
        for col in ["country_iso3", "country_name", "indicator_code",
                    "indicator_label", "source"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str).str.strip()

        # ── Drop rows still missing critical fields ────────────────────
        df = df.dropna(subset=["country_iso3", "indicator_code", "country_name"])
        df = df[df["country_iso3"] != ""]
        df = df[df["country_name"] != ""]
        df = df[df["indicator_code"] != ""]

        return df.reset_index(drop=True)[UNIFIED_COLUMNS]

    def _validate_columns(self, df: pd.DataFrame, source_label: str) -> None:
        """
        Raise ValueError if the raw DataFrame is missing any required column.
        This catches mismatches between collector output and the contract early.
        """
        missing = [col for col in UNIFIED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(
                f"{source_label} raw CSV is missing required columns: {missing}\n"
                f"Found columns: {list(df.columns)}\n"
                f"Expected columns: {UNIFIED_COLUMNS}"
            )
