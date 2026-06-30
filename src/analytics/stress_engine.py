"""
src/analytics/stress_engine.py
================================

PURPOSE
-------
Calculates a yearly Economic Stress Score for every country in the database.
This is the core business logic of the platform.

HOW IT WORKS — Production Robust Z-Score Pipeline
--------------------------------------------------

  Step 1 — Load
      Read economic_data from SQLite grouped by (country, year).
      Use the database as the single source of truth (never CSVs).

  Step 2 — Apply monotonic per-indicator transforms
      Before standardisation, each indicator is compressed via a
      variance-stabilising transform to reduce skewness and prevent
      extreme values from dominating the z-score scale:

          INFLATION_PCT     → sign(x) × log1p(|x|)   [signed-log]
          UNEMPLOYMENT_PCT  → log1p(x)
          GOVT_DEBT_PCT_GDP → x^(1/3)                 [cube root]
          INTEREST_RATE_PCT → log1p(x)
          GDP_GROWTH_PCT    → sign(x) × log1p(|x|)   [signed-log]

  Step 3 — Fit global robust statistics
      Compute median and IQR across ALL transformed observations
      (all countries, all years 2000–2024).  These become the reference
      frame for z-scoring.  Parameters are persisted to
      data/stress_model_params.json and reloaded on subsequent runs
      (delete the file to force a re-fit).

  Step 4 — Robust Z-score each indicator
      z = (T(x) − median) / (0.7413 × IQR)

      The 0.7413 correction constant makes the scale comparable to a
      standard deviation for normally distributed data (equivalent to
      sklearn.preprocessing.RobustScaler).

  Step 5 — Dynamic weight renormalization + composite
      Available-indicator weights are renormalised to sum to 1.0,
      then the composite is the weighted sum of z-scores:

          composite = Σ w*_i × z_i

      For records missing ≥ 2 indicators, a mild dampening factor
      (confidence_score^0.5) is applied to reflect reduced certainty
      while still scoring the record.

  Step 6 — Calibrate sigmoid alpha (automatic)
      α = ln(199) / P99(composite)

      This maps the 99th-percentile composite to 99.5% stress —
      keeping extreme crises clearly near the top without saturation.

  Step 7 — Sigmoid scaling
      stress_score = 100 / (1 + exp(−α × composite))

      Global, cross-year comparable. No per-year normalization.

  Step 8 — Classify and persist
      Risk levels: 0–30 Low Risk | 31–60 Medium Risk | 61–100 High Risk
      Persisted fields: raw_score (composite z-score), stress_score,
      risk_level, confidence_score, calculated_at.

IDEMPOTENCY
-----------
Uses INSERT OR REPLACE (UPSERT) on the UNIQUE(country_id, year) constraint.
Re-running the engine updates existing scores with fresh values — no duplicates.

IMPORTANT NOTES
---------------
- Multiple sources may report the same indicator for the same country-year
  (e.g., both World Bank and IMF report UNEMPLOYMENT_PCT for USA 2021).
  We average them: AVG(value) in the SQL query.
- Weights, required indicators, and the params file path are read from
  config/settings.py. Changing the formula requires only a settings change.
- The minimum indicator threshold remains 3. Records with 3–4 indicators
  receive a confidence_score < 1.0 and a mild dampening factor.

USAGE
-----
    from src.analytics.stress_engine import StressEngine

    engine = StressEngine()
    inserted, skipped = engine.run()

    # Force re-fit of global normalization parameters:
    inserted, skipped = engine.run(force_refit=True)
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config.settings as cfg
from src.database.db_manager import create_tables, ensure_confidence_column, get_connection

logger = logging.getLogger("platform.analytics")


# ── Public helper: risk classification ────────────────────────────────────────

def classify_risk(score: float) -> str:
    """
    Classify a normalised stress score (0–100) into a risk level string.

    Parameters
    ----------
    score : float
        A value in [0, 100].

    Returns
    -------
    str
        "Low Risk"    if score <=  30
        "Medium Risk" if score <=  60
        "High Risk"   if score >   60
    """
    if score <= cfg.RISK_LOW_MAX:
        return "Low Risk"
    if score <= cfg.RISK_MEDIUM_MAX:
        return "Medium Risk"
    return "High Risk"


# ── Monotonic per-indicator transforms ────────────────────────────────────────

def _signed_log(x: float) -> float:
    """sign(x) × log1p(|x|) — compresses magnitude while preserving sign."""
    return math.copysign(math.log1p(abs(x)), x)


def _cbrt(x: float) -> float:
    """Cube root: x^(1/3). Best skewness correction for government debt (σ=44%)."""
    return max(0.0, x) ** (1.0 / 3.0)


# Maps each indicator code → its transform function.
# GDP_GROWTH uses signed_log to preserve recession direction.
_TRANSFORMS: dict[str, object] = {
    "INFLATION_PCT":    _signed_log,
    "UNEMPLOYMENT_PCT": lambda x: math.log1p(max(0.0, x)),
    "GOVT_DEBT_PCT_GDP":_cbrt,
    "INTEREST_RATE_PCT":lambda x: math.log1p(max(0.0, x)),
    "GDP_GROWTH_PCT":   _signed_log,
}


# ── Internal data model for one country-year record ───────────────────────────

@dataclass
class CountryYearRecord:
    """Holds all indicator values for one (country_id, year) combination.

    After _apply_transforms_and_scale(), the `indicators` dict stores
    robust z-scores (not raw values).  compute_raw_score() then produces
    the weighted composite of those z-scores.
    """
    country_id:   int
    country_name: str
    year:         int
    indicators:   dict[str, float] = field(default_factory=dict)

    def compute_raw_score(self, weights: dict[str, float]) -> float:
        """
        Compute the weighted composite of indicator values (z-scores after
        the pipeline transforms).

        Weights are renormalized dynamically so they always sum to 1.0,
        correctly handling records with missing indicators.

        Returns 0.0 if no indicators are present or weights sum to zero.
        """
        available_weights = {
            code: w for code, w in weights.items()
            if code in self.indicators
        }
        sum_w = sum(available_weights.values())
        if abs(sum_w) < 1e-12:
            return 0.0

        adjusted_weights = {code: w / sum_w for code, w in available_weights.items()}
        return sum(
            adjusted_weights[code] * self.indicators[code]
            for code in adjusted_weights
        )


# ── The Engine ─────────────────────────────────────────────────────────────────

class StressEngine:
    """
    Computes, scales, and persists Economic Stress Scores for all
    country-year combinations available in the economic_data table.

    Usage
    -----
        engine = StressEngine()
        inserted, skipped = engine.run()

        # Re-fit normalization parameters from scratch:
        inserted, skipped = engine.run(force_refit=True)
    """

    def __init__(self) -> None:
        self.required = cfg.STRESS_INDICATORS   # list of canonical codes
        self.weights  = cfg.STRESS_WEIGHTS       # { code: weight }
        self._params_path: Path = cfg.STRESS_MODEL_PARAMS_PATH

    # ══════════════════════════════════════════════════════════════════════
    # Public entry point
    # ══════════════════════════════════════════════════════════════════════

    def run(self, force_refit: bool = False) -> tuple[int, int]:
        """
        Execute the full stress score pipeline:
            load → transform → fit params → z-score →
            composite → sigmoid → classify → persist

        Parameters
        ----------
        force_refit : bool
            If True, recompute normalization parameters from the full dataset
            even if stress_model_params.json already exists.
            Use when new ETL data significantly changes the distribution.

        Returns
        -------
        tuple[int, int]
            (inserted_or_updated, skipped_due_to_error)
        """
        logger.info("=" * 55)
        logger.info("  STRESS ENGINE — START")
        logger.info("=" * 55)

        import time
        t0 = time.perf_counter()

        # ── Ensure schema is up to date ────────────────────────────────
        create_tables()
        ensure_confidence_column()

        # ── Step 1: Load raw indicator data ───────────────────────────
        records = self._load_records()
        if not records:
            logger.error(
                "No country-year records found (>= 3 indicators). "
                "Ensure the ETL pipeline ran successfully first."
            )
            return 0, 0

        logger.info("Loaded %d country-year records.", len(records))

        # ── Step 2: Apply per-indicator monotonic transforms ──────────
        transformed = self._apply_transforms(records)

        # ── Step 3: Load or fit global normalization parameters ───────
        params = self._load_or_fit_params(transformed, force_refit)

        # ── Step 4: Compute robust z-scores ───────────────────────────
        z_records = self._apply_z_scores(transformed, params)

        # ── Step 5: Compute weighted composites ───────────────────────
        raw_scores: dict[tuple, float] = {
            (r.country_id, r.year): r.compute_raw_score(self.weights)
            for r in z_records
        }

        # ── Step 6–7: Sigmoid scale + classify ────────────────────────
        scored_records = self._normalise_and_classify(z_records, raw_scores, params)

        # ── Step 8: Persist to DB ──────────────────────────────────────
        inserted, errors = self._persist(scored_records)

        elapsed = time.perf_counter() - t0
        logger.info("=" * 55)
        logger.info("  STRESS ENGINE — COMPLETE")
        logger.info("  Inserted/updated : %d", inserted)
        logger.info("  Errors           : %d", errors)
        logger.info("  Elapsed          : %.2f s", elapsed)
        logger.info("=" * 55)

        return inserted, errors

    # ══════════════════════════════════════════════════════════════════════
    # Step 1: Load records from DB
    # ══════════════════════════════════════════════════════════════════════

    def _load_records(self) -> list[CountryYearRecord]:
        """
        Query economic_data for all required indicators, grouped by
        (country_id, year), and return CountryYearRecord objects that have
        at least 3 of the 5 required indicators present.

        Multiple sources for the same (country, indicator, year) are averaged
        via AVG() in SQL — preventing double-counting from World Bank + IMF.
        """
        sql = """
            SELECT
                c.id          AS country_id,
                c.name        AS country_name,
                ed.year       AS year,
                i.code        AS indicator_code,
                AVG(ed.value) AS value
            FROM economic_data ed
            JOIN countries  c ON ed.country_id   = c.id
            JOIN indicators i ON ed.indicator_id = i.id
            WHERE i.code IN ({placeholders})
            GROUP BY c.id, ed.year, i.code
            ORDER BY c.id, ed.year, i.code
        """.format(
            placeholders=", ".join("?" * len(self.required))
        )

        with get_connection() as conn:
            rows = conn.execute(sql, self.required).fetchall()

        # ── Group flat rows → {(country_id, year): CountryYearRecord} ──
        record_map: dict[tuple, CountryYearRecord] = {}
        for row in rows:
            key = (row["country_id"], row["year"])
            if key not in record_map:
                record_map[key] = CountryYearRecord(
                    country_id   = row["country_id"],
                    country_name = row["country_name"],
                    year         = row["year"],
                )
            record_map[key].indicators[row["indicator_code"]] = row["value"]

        # ── Filter: minimum 3 indicators required ─────────────────────
        complete: list[CountryYearRecord] = []
        skipped_log: list[tuple] = []

        for key, rec in record_map.items():
            if len(rec.indicators) < 3:
                missing = [i for i in self.required if i not in rec.indicators]
                skipped_log.append((rec.country_name, rec.year, missing))
            else:
                complete.append(rec)

        if skipped_log:
            unique_countries = {name for name, _, _ in skipped_log}
            logger.warning(
                "Skipped %d country-year records with < 3 indicators "
                "(affected countries: %s).",
                len(skipped_log),
                ", ".join(sorted(unique_countries)),
            )

        unique_countries_n = len({r.country_id for r in complete})
        unique_years_n     = len({r.year for r in complete})
        logger.info(
            "Complete records: %d | Countries: %d | Years: %d",
            len(complete), unique_countries_n, unique_years_n,
        )
        return complete

    # ══════════════════════════════════════════════════════════════════════
    # Step 2: Per-indicator monotonic transforms
    # ══════════════════════════════════════════════════════════════════════

    def _apply_transforms(
        self, records: list[CountryYearRecord]
    ) -> list[CountryYearRecord]:
        """
        Return new CountryYearRecord objects whose indicator values have been
        passed through variance-stabilising transforms.

        Transforms are applied BEFORE z-scoring so the IQR/median are
        computed on the symmetrised distribution, not the raw skewed one.

        Transform choice per indicator (empirically selected from live data):
            INFLATION     : signed_log  — skewness 63 → 0.33 after transform
            UNEMPLOYMENT  : log1p       — skewness  1.78 → -0.05
            GOVT_DEBT     : cbrt        — skewness  3.40 → -0.21 (best option)
            INTEREST_RATE : log1p       — skewness  4.42 → 0.24
            GDP_GROWTH    : signed_log  — preserves recession sign
        """
        import copy
        transformed: list[CountryYearRecord] = []
        for rec in records:
            new_rec = CountryYearRecord(
                country_id   = rec.country_id,
                country_name = rec.country_name,
                year         = rec.year,
            )
            for code, val in rec.indicators.items():
                fn = _TRANSFORMS.get(code)
                new_rec.indicators[code] = fn(val) if fn else val
            transformed.append(new_rec)
        return transformed

    # ══════════════════════════════════════════════════════════════════════
    # Step 3: Fit or load global normalization parameters
    # ══════════════════════════════════════════════════════════════════════

    def _load_or_fit_params(
        self,
        transformed_records: list[CountryYearRecord],
        force_refit: bool,
    ) -> dict:
        """
        Load fitted parameters from disk, or fit them from the current dataset.

        Parameters are fitted from ALL records (all countries, all years)
        to ensure cross-year comparability. They are saved to
        data/stress_model_params.json so that subsequent runs reuse the
        same reference frame.

        Pass force_refit=True (or delete the JSON file) to recompute.
        """
        if not force_refit and self._params_path.exists():
            try:
                with open(self._params_path, "r", encoding="utf-8") as f:
                    params = json.load(f)
                logger.info(
                    "Loaded stress model params from %s "
                    "(fitted on %s, N=%s).",
                    self._params_path.name,
                    params.get("computed_at", "unknown"),
                    params.get("n_records", "unknown"),
                )
                return params
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Params file corrupt (%s) — re-fitting.", exc)

        params = self._fit_params(transformed_records)
        self._params_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._params_path, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2)
        logger.info(
            "Fitted and saved stress model params to %s (N=%d).",
            self._params_path.name,
            params["n_records"],
        )
        return params

    def _fit_params(self, transformed_records: list[CountryYearRecord]) -> dict:
        """
        Compute global robust statistics from all transformed indicator values.

        For each indicator:
          - Collect all transformed values across every country-year
          - Compute median and IQR via linear-interpolation percentile
          - Compute scale = 0.7413 × IQR
            (0.7413 = 1/1.3490, normalizes IQR to σ units for normal data;
             equivalent to sklearn.preprocessing.RobustScaler)

        Then compute all composite z-scores and calibrate the sigmoid alpha.
        """
        # ── Collect transformed values per indicator ──────────────────
        all_vals: dict[str, list[float]] = {code: [] for code in self.weights}
        for rec in transformed_records:
            for code, val in rec.indicators.items():
                if code in all_vals:
                    all_vals[code].append(val)

        # ── Compute median, IQR, scale per indicator ──────────────────
        indicator_params: dict[str, dict] = {}
        for code, vals in all_vals.items():
            if not vals:
                continue
            sv    = sorted(vals)
            n     = len(sv)
            med   = self._percentile(sv, 50)
            q1    = self._percentile(sv, 25)
            q3    = self._percentile(sv, 75)
            iqr   = q3 - q1
            scale = 0.7413 * max(iqr, 1e-9)   # IQR correction constant
            indicator_params[code] = {
                "transform":  self._transform_name(code),
                "n":          n,
                "median":     round(med,   6),
                "q1":         round(q1,    6),
                "q3":         round(q3,    6),
                "iqr":        round(iqr,   6),
                "scale":      round(scale, 6),
            }

        # ── Compute all composites for sigmoid calibration ────────────
        composites: list[float] = []
        for rec in transformed_records:
            avail = {c: self.weights[c] for c in self.weights if c in rec.indicators}
            sw    = sum(avail.values())
            if abs(sw) < 1e-12:
                continue
            adj = {c: w / sw for c, w in avail.items()}
            comp = sum(
                adj[code] * (rec.indicators[code] - indicator_params[code]["median"])
                            / indicator_params[code]["scale"]
                for code in adj
                if code in indicator_params
            )
            composites.append(comp)

        alpha = self._calibrate_alpha(composites)

        return {
            "schema_version": "2.0",
            "computed_at":    datetime.now(timezone.utc).isoformat(),
            "n_records":      len(transformed_records),
            "fitting_method": (
                "global_robust_zscore_iqr_0.7413_cbrt_debt_sigmoid_p99"
            ),
            "sigmoid": {
                "alpha":         round(alpha, 6),
                "calibration":   "P99_composite_to_99.5_stress",
                "composite_p99": round(self._percentile(sorted(composites), 99), 6),
            },
            "indicators": indicator_params,
        }

    # ── Percentile (linear interpolation, numpy-compatible) ───────────

    @staticmethod
    def _percentile(sorted_vals: list[float], p: float) -> float:
        """
        Compute the p-th percentile using linear interpolation.

        Equivalent to numpy.percentile(..., interpolation='linear').
        Requires the input list to be pre-sorted ascending.
        """
        n = len(sorted_vals)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_vals[0]
        idx  = (p / 100.0) * (n - 1)
        lo   = int(idx)
        hi   = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])

    # ── Automatic sigmoid calibration ─────────────────────────────────

    @staticmethod
    def _calibrate_alpha(composites: list[float]) -> float:
        """
        Automatically choose the sigmoid steepness parameter alpha.

        Objective: map the 99th-percentile composite to 99.5% stress.

        Derivation:
            100 / (1 + exp(−α × P99)) = 99.5
            exp(−α × P99) = 0.5 / 99.5 = 1/199
            α = ln(199) / P99

        This keeps the top 1% of crisis country-years near (but not at)
        100%, preserving discrimination among extreme cases while preventing
        saturation.  Sudan (composite +6.20) and Zimbabwe (composite +5.87)
        both land very near 100 because both are genuinely far above P99.
        Use raw_score (composite z-score) to distinguish them.
        """
        if not composites:
            return 1.5   # sensible fallback
        p99 = StressEngine._percentile(sorted(composites), 99)
        if p99 <= 0:
            return 1.5
        return math.log(199.0) / p99

    @staticmethod
    def _transform_name(code: str) -> str:
        """Return the human-readable transform name for a given indicator code."""
        return {
            "INFLATION_PCT":    "signed_log",
            "UNEMPLOYMENT_PCT": "log1p",
            "GOVT_DEBT_PCT_GDP":"cbrt",
            "INTEREST_RATE_PCT":"log1p",
            "GDP_GROWTH_PCT":   "signed_log",
        }.get(code, "identity")

    # ══════════════════════════════════════════════════════════════════════
    # Step 4: Apply global z-scores
    # ══════════════════════════════════════════════════════════════════════

    def _apply_z_scores(
        self,
        transformed_records: list[CountryYearRecord],
        params: dict,
    ) -> list[CountryYearRecord]:
        """
        Replace each transformed indicator value with its robust z-score:

            z = (T(x) − median) / (0.7413 × IQR)

        Returns new CountryYearRecord objects whose `indicators` dict now
        holds z-scores.  compute_raw_score() on these records produces the
        weighted composite z-score (the raw_score stored in the DB).
        """
        ind_params = params["indicators"]
        import copy
        z_records: list[CountryYearRecord] = []
        for rec in transformed_records:
            new_rec = CountryYearRecord(
                country_id   = rec.country_id,
                country_name = rec.country_name,
                year         = rec.year,
            )
            for code, t_val in rec.indicators.items():
                if code not in ind_params:
                    continue
                p     = ind_params[code]
                scale = p["scale"]
                new_rec.indicators[code] = (t_val - p["median"]) / max(scale, 1e-12)
            z_records.append(new_rec)
        return z_records

    # ══════════════════════════════════════════════════════════════════════
    # Step 5-7: Sigmoid + classify
    # ══════════════════════════════════════════════════════════════════════

    def _normalise_and_classify(
        self,
        z_records: list[CountryYearRecord],
        raw_scores: dict[tuple, float],
        params: dict,
    ) -> list[dict]:
        """
        Convert composite z-scores to stress_score via sigmoid, then classify.

        Sigmoid formula:
            stress_score = 100 / (1 + exp(−α × composite))

        Alpha is loaded from fitted params (automatic, data-driven calibration).

        For records with fewer than 5 indicators, a mild dampening factor is
        applied to the composite before sigmoid conversion.  This pulls the
        stress score toward 50 (the neutral point) proportionally to missing
        data, reflecting reduced certainty rather than deleting the record:

            dampening = sqrt(n_available / 5)
            composite_dampened = composite × dampening

        Examples:
            5 indicators → dampening = 1.000 (no change)
            4 indicators → dampening = 0.894 (6% pull toward neutral)
            3 indicators → dampening = 0.775 (23% pull toward neutral)

        The undampened composite is still stored as raw_score for transparency.
        """
        alpha = params["sigmoid"]["alpha"]

        calculated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        result: list[dict] = []

        for rec in z_records:
            key      = (rec.country_id, rec.year)
            raw      = raw_scores[key]         # undampened composite z-score
            n_avail  = len(rec.indicators)
            conf     = round(n_avail / 5.0, 2)

            # ── Mild dampening for partial-data records ───────────────
            # sqrt(confidence) keeps 3-indicator records in the game
            # while applying a ~22% pull toward the neutral point (50%).
            dampening = math.sqrt(conf)
            composite_for_sigmoid = raw * dampening

            # ── Sigmoid → [0, 100] ────────────────────────────────────
            try:
                stress = 100.0 / (1.0 + math.exp(-alpha * composite_for_sigmoid))
            except OverflowError:
                stress = 100.0 if composite_for_sigmoid > 0 else 0.0
            stress = round(max(0.0, min(100.0, stress)), 4)

            result.append({
                "country_id":      rec.country_id,
                "country_name":    rec.country_name,
                "year":            rec.year,
                "raw_score":       round(raw, 6),     # undampened composite z-score
                "stress_score":    stress,
                "risk_level":      classify_risk(stress),
                "confidence_score":conf,
                "calculated_at":   calculated_at,
            })

        logger.info(
            "Sigmoid normalisation complete. alpha=%.4f | "
            "N=%d | score range=[%.2f, %.2f]",
            alpha,
            len(result),
            min(r["stress_score"] for r in result) if result else 0.0,
            max(r["stress_score"] for r in result) if result else 0.0,
        )
        return result

    # ══════════════════════════════════════════════════════════════════════
    # Step 8: Persist
    # ══════════════════════════════════════════════════════════════════════

    def _persist(self, scored_records: list[dict]) -> tuple[int, int]:
        """
        Write stress scores to the stress_scores table using INSERT OR REPLACE.

        INSERT OR REPLACE is equivalent to:
          - INSERT if (country_id, year) not in table
          - DELETE old row + INSERT new row if it already exists

        This guarantees idempotency: re-running the engine always produces
        up-to-date scores, never duplicates.

        Returns (inserted_or_updated, errors).
        """
        inserted = 0
        errors   = 0

        with get_connection() as conn:
            for rec in scored_records:
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO stress_scores
                            (country_id, year, raw_score, stress_score,
                             risk_level, calculated_at, confidence_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rec["country_id"],
                            rec["year"],
                            rec["raw_score"],
                            rec["stress_score"],
                            rec["risk_level"],
                            rec["calculated_at"],
                            rec["confidence_score"],
                        ),
                    )
                    inserted += 1
                except Exception as exc:
                    logger.error(
                        "Failed to insert score for %s %d: %s",
                        rec["country_name"], rec["year"], exc,
                    )
                    errors += 1
            conn.commit()

        # ── Summary ──────────────────────────────────────────────────
        from collections import Counter
        risk_counts = Counter(r["risk_level"] for r in scored_records)
        full_data   = sum(1 for r in scored_records if r["confidence_score"] >= 1.0)
        partial     = len(scored_records) - full_data

        logger.info(
            "Risk distribution: Low=%d | Medium=%d | High=%d",
            risk_counts.get("Low Risk",    0),
            risk_counts.get("Medium Risk", 0),
            risk_counts.get("High Risk",   0),
        )
        logger.info(
            "Coverage: Full(5/5)=%d | Partial(<5)=%d | Total=%d",
            full_data, partial, len(scored_records),
        )
        return inserted, errors
