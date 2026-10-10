"""Temporal contracts for the measurement-anchored arrival research adapter."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.arrival_model import POLICY_VERSION, arrival_forecast


class ValueModel:
    def predict(self, x):
        return x[:, 0] + 8 + x[:, 8] * 2


class RiskModel:
    def predict_proba(self, x):
        return np.tile([.1, .9], (len(x), 1))


def bundle():
    return {"models": {30: ValueModel(), 60: ValueModel()}, "classifiers": {30: RiskModel(), 60: RiskModel()},
            "probability_calibrators": {}, "alert_thresholds": {30: .7, 60: .7},
            "intervals": {"population": {30: 10., 60: 15.}, "hybrid": {30: 10., 60: 15.}},
            "metadata": {"version": "test", "primary": "hybrid"}}


def rows(count=8, delay=1, cadence=15):
    start = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(minutes=i * cadence)).isoformat(),
             "available_at": (start + timedelta(minutes=i * cadence + delay)).isoformat(),
             "glucose_mg_dl": 120. + i * 3} for i in range(count)]


def run(readings=None, delay=1, **kwargs):
    readings = rows(delay=delay) if readings is None else readings
    return arrival_forecast(readings, {"patient_id": "p", "age": 50}, readings[-1]["available_at"],
                            bundle=bundle(), source_timezone="UTC", **kwargs)


@pytest.mark.parametrize("delay,lead", [(0, 30), (1, 29), (5, 25), (20, 10)])
def test_positive_delay_keeps_actual_issue_and_measurement_target(delay, lead):
    readings = rows(delay=delay)
    result = run(readings)
    assert result["quality"]["status"] == "ok"
    point = result["forecasts"]["hybrid"][0]
    assert point["issued_at"] == readings[-1]["available_at"]
    assert point["data_cutoff_at"] == readings[-1]["timestamp"]
    assert point["remaining_lead_minutes"] == lead
    assert not result["clinical_queue_eligible"]


@pytest.mark.parametrize("delay,eligible", [(0, True), (1, True), (5, True), (6, False), (14, False)])
def test_research_warning_checks_first_event_target_lead(delay, eligible):
    result = run(delay=delay)
    risk = result["event_risks"][0]
    assert risk["earliest_remaining_lead_minutes"] == 15 - delay
    assert result["research_review_eligible"] is eligible
    assert not risk["clinical_queue_eligible"]


@pytest.mark.parametrize("delay", [15, 20])
def test_past_or_current_original_event_target_suppresses_probability(delay):
    result = run(delay=delay)
    assert result["event_risks"] == []
    assert "event_30_window_contains_past_target" in result["suppression_reasons"]
    assert not result["research_review_eligible"]


def test_non_synthetic_source_cannot_open_research_or_clinical_queue():
    result = run(source_kind="clinic")
    assert result["event_risks"][0]["exceeds_threshold"]
    assert not result["research_review_eligible"]
    assert not result["clinical_queue_eligible"]
    assert result["temporal"]["untimed_baseline_context_policy"] == "excluded"


def test_five_minute_source_is_unsupported_not_resampled():
    result = run(rows(cadence=5))
    assert result["quality"]["status"] == "unsupported_cadence"
    assert not result["forecasts"]["population"]


def test_native_gap_pauses_and_reordering_does_not_change_snapshot():
    readings = rows()
    expected = run(readings)
    reversed_result = arrival_forecast(list(reversed(readings)), {"patient_id": "p", "age": 50},
                                      readings[-1]["available_at"], bundle=bundle(), source_timezone="UTC")
    assert reversed_result == expected
    missing = readings[:5] + readings[6:]
    assert run(missing)["quality"]["status"] == "gap"


def test_naive_receipt_and_conflicting_readings_are_rejected():
    readings = rows()
    readings[2]["available_at"] = readings[2]["available_at"].replace("+00:00", "")
    with pytest.raises(ValueError, match="timezone"):
        run(readings)
    readings = rows()
    readings.insert(4, {**readings[3], "glucose_mg_dl": 190})
    with pytest.raises(ValueError, match="Conflicting"):
        run(readings)


def test_future_and_unavailable_data_never_change_forecast():
    readings = rows()
    expected = run(readings)
    unavailable = {"timestamp": readings[-1]["timestamp"], "available_at": "2026-10-11T00:00:00Z", "glucose_mg_dl": 9999}
    future = {"timestamp": "2026-10-11T00:00:00Z", "available_at": "2026-10-11T00:01:00Z", "glucose_mg_dl": 9999}
    result = arrival_forecast(readings + [future, unavailable], {"patient_id": "p", "age": 50},
                             readings[-1]["available_at"], bundle=bundle(), source_timezone="UTC")
    assert result == expected


def issued_pair():
    forecast = {"forecast_id": "f1", "patient_id": "p", "issued_at": "2026-10-10T09:01:00Z", "target_at": "2026-10-10T09:30:00Z",
                "horizon_minutes": 30, "population_mg_dl": 120, "model_version": f"test:{POLICY_VERSION}"}
    outcome = {"forecast_id": "f1", "patient_id": "p", "target_at": forecast["target_at"], "horizon_minutes": 30,
               "glucose_mg_dl": 150, "available_at": "2026-10-10T09:31:00Z"}
    return forecast, outcome


def test_no_imaginary_historical_forecasts_or_unissued_updates():
    assert run()["adaptation"]["matured_samples"] == 0
    forecast, outcome = issued_pair()
    assert run(outcomes=[outcome])["adaptation"]["matured_samples"] == 0
    assert run(issued_forecasts=[forecast])["adaptation"]["matured_samples"] == 0
    result = run(issued_forecasts=[forecast], outcomes=[outcome])
    assert result["adaptation"]["matured_samples"] == 1
    assert result["adaptation"]["correction_mg_dl"] == pytest.approx(30 / 25)


def test_late_outcome_foreign_patient_and_old_model_cannot_update():
    forecast, outcome = issued_pair()
    assert run(issued_forecasts=[forecast], outcomes=[{**outcome, "available_at": "2026-10-11T00:00:00Z"}])["adaptation"]["matured_samples"] == 0
    assert run(issued_forecasts=[{**forecast, "patient_id": "other"}], outcomes=[outcome])["adaptation"]["matured_samples"] == 0
    assert run(issued_forecasts=[{**forecast, "model_version": "test"}], outcomes=[outcome])["adaptation"]["matured_samples"] == 0
    assert run(issued_forecasts=[forecast], outcomes=[{**outcome, "observed_at": "2026-10-10T09:45:00Z"}])["adaptation"]["matured_samples"] == 0


def test_duplicate_delivery_and_repeated_target_do_not_inflate_adaptation():
    forecast, outcome = issued_pair()
    second = {**forecast, "forecast_id": "f2", "issued_at": "2026-10-10T09:02:00Z"}
    result = run(issued_forecasts=[forecast, forecast, second], outcomes=[outcome, outcome, {**outcome, "forecast_id": "f2"}])
    assert result["adaptation"]["matured_samples"] == 1
    assert result["adaptation"]["correction_mg_dl"] == pytest.approx(30 / 25)


def test_timezone_feature_policy_is_visible_and_does_not_move_targets():
    readings = rows()
    utc = arrival_forecast(readings, {"patient_id": "p"}, readings[-1]["available_at"], bundle=bundle(), source_timezone="UTC")
    india = arrival_forecast(readings, {"patient_id": "p"}, readings[-1]["available_at"], bundle=bundle(), source_timezone="Asia/Kolkata")
    assert utc["forecasts"]["population"][0]["target_at"] == india["forecasts"]["population"][0]["target_at"]
    assert utc["forecasts"]["population"][0]["glucose_mg_dl"] != india["forecasts"]["population"][0]["glucose_mg_dl"]
    assert india["temporal"]["clock_compatibility"].startswith("unvalidated")
    assert not india["model"]["legacy_scores_transfer"]


def test_correction_bounds_and_receipt_before_measurement():
    forecast, outcome = issued_pair()
    bad = {**outcome, "available_at": "2026-10-10T09:00:00Z"}
    assert run(issued_forecasts=[forecast], outcomes=[bad])["adaptation"]["matured_samples"] == 0
    readings = rows()
    readings[0]["available_at"] = "2026-10-10T08:59:00Z"
    with pytest.raises(ValueError, match="precede"):
        run(readings)


def test_arrival_primary_does_not_transfer_legacy_selection():
    b = bundle()
    b["metadata"]["primary"] = "hybrid"
    readings = rows()
    result = arrival_forecast(readings, {"patient_id": "p"}, readings[-1]["available_at"], bundle=b)
    assert result["model"]["primary"] == "population"
    assert result["model"]["legacy_primary"] == "hybrid"
    assert result["model"]["personalization_status"] == "experimental_arrival_mode"
    assert not result["model"]["legacy_scores_transfer"]
    assert not result["forecasts"]["population"][0]["coverage_established_for_arrival_mode"]


def test_stale_measurement_pauses_and_exact_target_receipt_matures():
    readings = rows()
    later = (datetime.fromisoformat(readings[-1]["timestamp"]) + timedelta(minutes=21)).isoformat()
    paused = arrival_forecast(readings, {"patient_id": "p"}, later, bundle=bundle())
    assert paused["quality"]["status"] == "stale"
    assert paused["event_risks"] == []
    forecast, outcome = issued_pair()
    result = arrival_forecast(rows(3), {"patient_id": "p"}, outcome["available_at"], [forecast], [outcome], bundle=bundle())
    assert result["adaptation"]["matured_samples"] == 1


def test_late_historical_context_and_supplied_ledgers_are_not_mutated():
    import copy
    readings = rows()
    forecast, outcome = issued_pair()
    ledger, outcomes = [forecast], [outcome]
    before = copy.deepcopy((readings, ledger, outcomes))
    profile = {"patient_id": "p", "baseline_context": {"age": 50}, "context_entries": [
        {"kind": "historical", "value": {"age": 90}, "observed_at": readings[0]["timestamp"], "available_at": "2026-10-11T00:00:00Z"}]}
    arrival_forecast(readings, profile, readings[-1]["available_at"], ledger, outcomes, bundle=bundle())
    assert (readings, ledger, outcomes) == before


def test_residual_clip_and_correction_bound_with_many_actual_targets():
    start = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    ledger, outcomes = [], []
    for index in range(100):
        target = start + timedelta(minutes=15 * index)
        ledger.append({"forecast_id": str(index), "patient_id": "p", "issued_at": (target - timedelta(minutes=29)).isoformat(),
                       "target_at": target.isoformat(), "horizon_minutes": 30, "population_mg_dl": 20, "model_version": f"test:{POLICY_VERSION}"})
        outcomes.append({"forecast_id": str(index), "patient_id": "p", "target_at": target.isoformat(), "horizon_minutes": 30,
                         "glucose_mg_dl": 600, "available_at": (target + timedelta(minutes=1)).isoformat()})
    result = run(issued_forecasts=ledger, outcomes=outcomes)
    assert result["adaptation"]["matured_samples"] == 100
    assert result["adaptation"]["correction_mg_dl"] == 20
    assert all(item["residual_mg_dl"] == 60 for item in result["adaptation"]["history"])
