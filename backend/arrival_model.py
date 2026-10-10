"""Arrival-time research adapter. It does not create a validated live CGM model.

The saved model's targets stay measurement anchored. Every issuance uses the
actual server clock; adaptation consumes only supplied, actually issued pairs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
from math import cos, pi, sin
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from threadpoolctl import threadpool_limits

from backend.hybrid import ADAPTATION, calibrated_probabilities, context_at, load_clinic_bundle
from backend.twin import HORIZONS, extract_features

POLICY_VERSION = "arrival-research-v1"
MODE = "measurement_anchored_arrival_research"
MIN_RESEARCH_LEAD_MINUTES = 10.0
MAX_MEASUREMENT_AGE_MINUTES = 20.0
ROOT = Path(__file__).resolve().parents[1]


def utc_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Arrival mode requires timezone-explicit timestamps.")
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def artifact_checksum() -> str:
    return hashlib.sha256((ROOT / "data/processed/clinic_model.joblib").read_bytes()).hexdigest()


def _available(readings: list[dict], issued: datetime, patient_id: str) -> list[dict]:
    selected = {}
    for reading in readings:
        observed = utc_time(reading.get("timestamp") or reading.get("observed_at"))
        available = utc_time(reading.get("server_received_at") or reading.get("available_at"))
        if observed > issued or available > issued:
            continue
        if reading.get("patient_id") is not None and str(reading["patient_id"]) != patient_id:
            raise ValueError("Reading belongs to a different patient.")
        if available < observed:
            raise ValueError("Receipt cannot precede measurement in arrival mode.")
        value = float(reading["glucose_mg_dl"])
        if not np.isfinite(value) or not 20 <= value <= 600:
            raise ValueError("Glucose must be finite and between 20 and 600 mg/dL.")
        entry = {"timestamp": observed.isoformat(), "available_at": available.isoformat(), "glucose_mg_dl": value}
        existing = selected.get(observed)
        if existing and existing["glucose_mg_dl"] != value:
            raise ValueError("Conflicting measurements require intake resolution.")
        # Redelivery cannot postpone the first known availability of a reading.
        if existing is None or utc_time(existing["available_at"]) > available:
            selected[observed] = entry
    return [selected[key] for key in sorted(selected)]


def _quality(rows: list[dict], issued: datetime) -> dict:
    if not rows:
        return {"status": "warming_up", "message": "Waiting for measured readings with trusted receipt times.",
                "last_reading_at": None, "minutes_since_reading": None}
    last = utc_time(rows[-1]["timestamp"])
    age = (issued - last).total_seconds() / 60
    common = {"last_reading_at": last.isoformat(), "minutes_since_reading": age, "native_sampling_minutes": 15}
    if age > MAX_MEASUREMENT_AGE_MINUTES:
        return {**common, "status": "stale", "message": "Measurement is too old for this research adapter; forecasts paused."}
    if len(rows) < 5:
        return {**common, "status": "warming_up", "message": "Five actual 15-minute measurements are required."}
    intervals = [(utc_time(b["timestamp"]) - utc_time(a["timestamp"])).total_seconds()
                 for a, b in zip(rows[-5:], rows[-4:])]
    if any(abs(interval - 900) > 1 for interval in intervals):
        native_gaps = all(interval >= 899 and abs(interval / 900 - round(interval / 900)) < .002 for interval in intervals)
        status = "gap" if native_gaps else "unsupported_cadence"
        return {**common, "status": status, "message": "Model requires native 15-minute history; no interpolation or automatic resampling is performed."}
    return {**common, "status": "ok", "message": "Arrival-aware research estimate; targets remain measurement anchored."}


def _corrections(issued_forecasts: list[dict], outcomes: list[dict], issued: datetime,
                 patient_id: str, model_version: str, parameters: dict) -> dict:
    matched = {}
    for outcome in outcomes:
        if str(outcome.get("patient_id", "")) != patient_id:
            continue
        try:
            target = utc_time(outcome["target_at"])
            available = utc_time(outcome.get("available_at") or outcome.get("server_received_at"))
            observed = utc_time(outcome.get("observed_at") or outcome["target_at"])
            value = float(outcome["glucose_mg_dl"])
            horizon = int(outcome["horizon_minutes"])
        except (KeyError, TypeError, ValueError):
            continue
        if observed != target or available < observed or available > issued or observed > issued or not np.isfinite(value) or not 20 <= value <= 600:
            continue
        key = (str(outcome.get("forecast_id", "")), horizon, target)
        old = matched.get(key)
        if old and old[1] != value:
            raise ValueError("Conflicting forecast outcomes require intake resolution.")
        if old is None or available < old[0]:
            matched[key] = (available, value)
    pairs = {h: [] for h in HORIZONS}
    for forecast in issued_forecasts:
        if str(forecast.get("patient_id", "")) != patient_id or forecast.get("model_version") != model_version:
            continue
        try:
            origin = utc_time(forecast["issued_at"])
            target = utc_time(forecast["target_at"])
            horizon = int(forecast["horizon_minutes"])
            population = float(forecast["population_mg_dl"])
        except (KeyError, TypeError, ValueError):
            continue
        outcome = matched.get((str(forecast.get("forecast_id", "")), horizon, target))
        if horizon not in pairs or not outcome or not origin < target or not origin <= issued or not origin < outcome[0] or not np.isfinite(population):
            continue
        pairs[horizon].append((outcome[0], origin, target, str(forecast.get("forecast_id", "")), outcome[1] - population))
    result = {}
    for horizon, entries in pairs.items():
        residual_sum = weight = 0.0
        history, seen = [], set()
        # One target/outcome per horizon: repeated polling must not inflate learning.
        for available, origin, target, identifier, residual in sorted(entries):
            if target in seen:
                continue
            seen.add(target)
            clipped = float(np.clip(residual, -parameters["residual_clip"], parameters["residual_clip"]))
            residual_sum = parameters["decay"] * residual_sum + clipped
            weight = parameters["decay"] * weight + 1
            correction = float(np.clip(residual_sum / (weight + parameters["prior_weight"]),
                                       -parameters["max_correction"], parameters["max_correction"]))
            history.append({"forecast_id": identifier, "forecast_issued_at": origin.isoformat(), "target_at": target.isoformat(),
                            "available_at": available.isoformat(), "residual_mg_dl": clipped, "correction_mg_dl": correction})
        result[horizon] = {"horizon_minutes": horizon, "matured_samples": len(history), "effective_weight": weight,
                           "correction_mg_dl": history[-1]["correction_mg_dl"] if history else 0.0, "history": history[-24:]}
    return result


def arrival_forecast(observations: list[dict], profile: dict, issued_at: str,
                     issued_forecasts: list[dict] | None = None, outcomes: list[dict] | None = None,
                     bundle: dict | None = None, source_timezone: str | None = None,
                     source_kind: str = "synthetic") -> dict:
    """Pure arrival forecast. Clinical queue eligibility is deliberately always false.

    Ledger entries: forecast_id, patient_id, issued_at, target_at, horizon_minutes,
    population_mg_dl, model_version. Outcomes: forecast_id, patient_id, target_at,
    horizon_minutes, glucose_mg_dl, available_at. Identity must also be checked by
    the authenticated caller. No historical forecasts are synthesized here.
    """
    issued = utc_time(issued_at)
    patient_id = str(profile.get("patient_id") or profile.get("id") or "")
    if not patient_id:
        raise ValueError("Arrival forecasting requires a patient ID.")
    timezone_info = None
    if source_timezone:
        try:
            timezone_info = ZoneInfo(source_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown source timezone.") from error
    original_bundle = load_clinic_bundle() if bundle is None else bundle
    fold = original_bundle.get("patient_folds", {}).get(patient_id)
    selected = original_bundle.get("fold_bundles", {}).get(fold, original_bundle)
    metadata = selected.get("metadata", {})
    trained_version = metadata.get("version", "clinic-model-unavailable")
    model_version = f"{trained_version}:{POLICY_VERSION}"
    parameters = {**ADAPTATION, **selected.get("adaptation", {})}
    rows = _available(observations, issued, patient_id)
    quality = _quality(rows, issued)
    correction = _corrections(issued_forecasts or [], outcomes or [], issued, patient_id, model_version, parameters)
    current_state = correction[30]
    result = {"quality": quality, "forecasts": {"population": [], "hybrid": []}, "event_risks": [],
              "model": {"version": model_version, "trained_model_version": trained_version, "primary": "population",
                        "legacy_primary": metadata.get("primary", "population"), "personalization_status": "experimental_arrival_mode",
                        "mode": MODE, "policy_version": POLICY_VERSION, "artifact_sha256": artifact_checksum() if bundle is None else None,
                        "evidence": "measurement-anchored research adapter; no device or clinical validation",
                        "legacy_scores_transfer": False},
              "adaptation": {**current_state, "by_horizon": list(correction.values()), "parameters": parameters,
                             "maturity": "adapted" if current_state["matured_samples"] >= 24 else "warming_up",
                             "message": "Only supplied actual issuances and arrived matching outcomes update correction.",
                             "engineering_state": {"level": rows[-1]["glucose_mg_dl"] if rows else None,
                                 "trend_mg_dl_per_15_minutes": rows[-1]["glucose_mg_dl"] - rows[-2]["glucose_mg_dl"] if len(rows) > 1 else None,
                                 "volatility_mg_dl": float(np.std([r["glucose_mg_dl"] for r in rows[-5:]])) if rows else None,
                                 "readings": len(rows)}},
              "temporal": {"issued_at": issued.isoformat(), "data_cutoff_at": rows[-1]["timestamp"] if rows else None,
                           "measurement_age_minutes": quality["minutes_since_reading"], "target_anchor": "latest_measurement",
                           "source_timezone": source_timezone, "feature_clock": "source_local" if timezone_info else "UTC_unverified_fallback",
                           "clock_compatibility": "unvalidated_against_dataset_local_training_clock",
                           "minimum_research_lead_minutes": MIN_RESEARCH_LEAD_MINUTES,
                           "original_event_target_times": {str(h): [(utc_time(rows[-1]["timestamp"]) + timedelta(minutes=s)).isoformat()
                               for s in range(15, h + 1, 15)] for h in HORIZONS} if rows else {}},
              "source_kind": source_kind, "research_review_eligible": False, "clinical_queue_eligible": False,
              "suppression_reasons": []}
    if quality["status"] != "ok" or not selected.get("models"):
        result["suppression_reasons"].append(quality["status"] if quality["status"] != "ok" else "model_unavailable")
        return result
    anchor = utc_time(rows[-1]["timestamp"])
    dated_profile = dict(profile)
    baseline = dated_profile.get("baseline_context", dated_profile)
    is_clinic = source_kind in {"clinic", "real", "authorized_clinic"}
    if is_clinic and not (baseline.get("available_at") or baseline.get("context_available_at")):
        dated_profile["baseline_context"] = {}
    context = context_at(dated_profile, issued.isoformat())
    features = extract_features(rows[-5:], context).reshape(1, -1)
    local_anchor = anchor.astimezone(timezone_info) if timezone_info else anchor
    hour = local_anchor.hour + local_anchor.minute / 60
    features[0, 8:10] = [sin(2 * pi * hour / 24), cos(2 * pi * hour / 24)]
    result["temporal"]["untimed_baseline_context_policy"] = "excluded" if is_clinic else "public_or_synthetic_baseline_assumption"
    with threadpool_limits(limits=1):
        for horizon in HORIZONS:
            regressor = selected["models"].get(horizon)
            if regressor is None:
                continue
            target = anchor + timedelta(minutes=horizon)
            remaining = (target - issued).total_seconds() / 60
            if remaining < MIN_RESEARCH_LEAD_MINUTES:
                result["suppression_reasons"].append(f"endpoint_{horizon}_insufficient_remaining_lead")
                continue
            base = float(regressor.predict(features)[0])
            values = {"population": base, "hybrid": base + correction[horizon]["correction_mg_dl"]}
            for name, center in values.items():
                width = selected.get("intervals", {}).get(name, {}).get(horizon)
                result["forecasts"][name].append({"issued_at": issued.isoformat(), "timestamp": target.isoformat(),
                    "target_at": target.isoformat(), "data_cutoff_at": anchor.isoformat(), "horizon_minutes": horizon,
                    "remaining_lead_minutes": remaining, "glucose_mg_dl": center,
                    "lower": max(0, center - width) if width is not None else None, "upper": center + width if width is not None else None,
                    "interval_method": "legacy_empirical_width_unvalidated_for_arrival_mode", "nominal_coverage": .90,
                    "coverage_established_for_arrival_mode": False, "model_version": model_version})
            event_targets = [anchor + timedelta(minutes=step) for step in range(15, horizon + 1, 15)]
            if any(point <= issued for point in event_targets):
                result["suppression_reasons"].append(f"event_{horizon}_window_contains_past_target")
                continue
            classifier = selected.get("classifiers", {}).get(horizon)
            if classifier is None:
                continue
            probability = float(calibrated_probabilities(classifier, selected.get("probability_calibrators", {}).get(horizon), features)[0])
            threshold = float(selected.get("alert_thresholds", {}).get(horizon, 1.01))
            earliest_lead = (event_targets[0] - issued).total_seconds() / 60
            enough_lead = earliest_lead >= MIN_RESEARCH_LEAD_MINUTES
            eligible = rows[-1]["glucose_mg_dl"] <= 180
            exceeds = bool(eligible and probability >= threshold)
            research_eligible = bool(source_kind == "synthetic" and horizon == 30 and exceeds and enough_lead)
            result["event_risks"].append({"horizon_minutes": horizon, "probability": probability, "threshold": threshold,
                "exceeds_threshold": exceeds, "event_eligible": eligible, "ongoing_high": not eligible,
                "event_target_times": [point.isoformat() for point in event_targets], "issued_at": issued.isoformat(),
                "window_end_at": target.isoformat(), "earliest_remaining_lead_minutes": earliest_lead,
                "remaining_lead_minutes": remaining, "research_review_eligible": research_eligible,
                "clinical_queue_eligible": False, "warning_supported": enough_lead,
                "target": "above 180 at one of the listed future scheduled native readings; not next 30 minutes from issuance",
                "probability_method": "legacy_logistic_calibration_unvalidated_for_arrival_mode"})
            result["research_review_eligible"] |= research_eligible
            if not enough_lead:
                result["suppression_reasons"].append(f"event_{horizon}_insufficient_earliest_lead")
    return result
