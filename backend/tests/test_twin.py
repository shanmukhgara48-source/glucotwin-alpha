from datetime import datetime, timedelta

import numpy as np
from fastapi.testclient import TestClient

from backend.main import app, build_snapshot, clean_json
from backend.twin import FEATURE_NAMES, TwinFilter, extract_features, forecast_prefix, predict_stream


def records(count=120, base=130, phase=0):
    start = datetime(2020, 1, 1)
    return [{"timestamp": (start + timedelta(minutes=15 * index)).isoformat(),
             "glucose_mg_dl": base + 20 * np.sin(index / 5 + phase)} for index in range(count)]


PROFILE = {"id": "research-A", "age": 55, "bmi": 26, "sex": "Female", "diabetes_duration_years": 8}


def test_mutating_future_cannot_change_earlier_snapshot():
    original = records()
    changed = [dict(row) for row in original]
    for row in changed[41:]:
        row["glucose_mg_dl"] = 350
    before = build_snapshot(PROFILE, original, cursor=40)
    after = build_snapshot(PROFILE, changed, cursor=40)
    assert before == after
    assert all(row["timestamp"] <= before["current_time"] for row in before["observations"])


def test_forecast_history_actual_is_revealed_only_at_target_time():
    snapshot = build_snapshot(PROFILE, records(), cursor=20)
    future = [point for point in snapshot["forecast_history"] if point["target_time"] > snapshot["current_time"]]
    past = [point for point in snapshot["forecast_history"] if point["target_time"] <= snapshot["current_time"]]
    assert future and all(point["actual"] is None for point in future)
    assert past and all(point["actual"] is not None for point in past)


def test_patients_have_independent_state():
    first = forecast_prefix(records(base=100)[:60], PROFILE)
    other = forecast_prefix(records(base=220, phase=1)[:60], {**PROFILE, "id": "research-B"})
    repeated = forecast_prefix(records(base=100)[:60], PROFILE)
    assert first == repeated
    assert other["state"]["level"] != first["state"]["level"]


def test_sensor_gap_suppresses_forecasts_and_recent_actuals():
    snapshot = build_snapshot(PROFILE, records(), cursor=40, scenario="sensor_gap")
    assert snapshot["quality"]["status"] == "gap"
    assert snapshot["quality"]["minutes_since_reading"] == 45
    assert snapshot["forecasts"] == {"twin": [], "population": []}
    assert snapshot["alerts"] == []
    assert len(snapshot["observations"]) == 38
    hidden_time = records()[40]["timestamp"]
    assert all(point["actual"] is None for point in snapshot["forecast_history"] if point["target_time"] == hidden_time)


def test_natural_gap_needs_consecutive_readings_to_recover():
    rows = records(12)
    rows = rows[:5] + rows[8:]
    assert forecast_prefix(rows[:6])["quality"]["status"] == "gap"
    assert forecast_prefix(rows)["quality"]["status"] == "gap"
    assert forecast_prefix(records(4))["quality"]["status"] == "warming_up"


def test_online_adaptation_changes_parameters_and_same_filter_ablation_is_fixed():
    rows = records()
    adapted = forecast_prefix(rows, adapt=True)
    pooled = forecast_prefix(rows, adapt=False)
    assert adapted["state"]["adaptation_samples"] > 0
    assert pooled["state"]["adaptation_samples"] == 0
    assert adapted["state"]["parameters"] != pooled["state"]["parameters"]
    assert pooled["state"]["parameters"]["damping"] == 0.75
    assert adapted["forecasts"]["twin"][0]["glucose_mg_dl"] != pooled["forecasts"]["twin"][0]["glucose_mg_dl"]


def test_stream_matches_independent_prefix_and_intervals_are_ordered():
    rows = records(40)
    stream = predict_stream(rows)
    prefix = forecast_prefix(rows[:21])
    assert stream[20]["forecasts"] == prefix["forecasts"]["twin"]
    for forecast in prefix["forecasts"]["twin"]:
        assert forecast["lower"] < forecast["glucose_mg_dl"] < forecast["upper"]
        assert forecast["interval_method"] == "uncalibrated_gaussian_state_model"


def test_calibration_is_used_without_fabricating_coverage():
    result = forecast_prefix(records(), interval_calibration={30: {"residual_quantile": 25}, 60: {"residual_quantile": 40}})
    thirty = result["forecasts"]["twin"][0]
    assert thirty["upper"] - thirty["glucose_mg_dl"] == 25
    assert thirty["interval_method"] == "validation_residual_quantile"
    assert result["intervals"]["twin_calibrated"] is True


def test_feature_contract_and_missing_context_are_valid():
    feature_row = extract_features(records(5), PROFILE)
    assert len(feature_row) == len(FEATURE_NAMES)
    assert np.isfinite(feature_row).all()
    assert np.isnan(extract_features(records(5))[-4:]).any()


def test_duplicate_or_reversed_timestamps_are_rejected():
    twin = TwinFilter()
    twin.update(130, "2020-01-01T12:00:00")
    try:
        twin.update(135, "2020-01-01T12:00:00")
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate timestamps should fail")


def test_api_error_shape_and_nan_serialization():
    client = TestClient(app)
    result = client.get("/api/replay/missing?cursor=-1")
    assert result.status_code == 422
    assert "error" in result.json()
    assert clean_json({"missing": float("nan")}) == {"missing": None}
