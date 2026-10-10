"""Local, stateless FastAPI service for recorded ShanghaiT2DM replay."""
from __future__ import annotations

import csv
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.twin import forecast_prefix, parse_time, population_forecasts, predict_stream

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("GLUCOTWIN_DATA_DIR", APP_ROOT / "data" / "processed"))
app = FastAPI(title="GlucoTwin", version="0.1.0", description="Recorded research prototype; no clinical validation.")
# TODO: add auth before exposing real health records or deploying beyond localhost.


def clean_json(value: Any) -> Any:
    """Missing metrics are null, never invalid JSON NaN or infinity."""
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return clean_json(value.item())
    return value


def success(data: Any) -> dict:
    return {"success": True, "data": clean_json(data)}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid request parameters."})


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


def read_json(name: str, fallback: Any = None) -> Any:
    path = DATA_DIR / name
    return json.loads(path.read_text()) if path.exists() else fallback


@lru_cache(maxsize=1)
def data_store() -> dict:
    patients = read_json("patients.json", [])
    observations: dict[str, list[dict]] = {str(patient["id"]): [] for patient in patients}
    primary = {str(patient["id"]): str(patient["recording_id"]) for patient in patients}
    path = DATA_DIR / "observations.csv"
    if path.exists():
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                patient_id = str(row["patient_id"])
                if patient_id not in primary or str(row["recording_id"]) != primary[patient_id]:
                    continue
                observations[patient_id].append({"timestamp": row["timestamp"], "glucose_mg_dl": float(row["glucose_mg_dl"])})
    for patient_id in observations:
        observations[patient_id].sort(key=lambda row: parse_time(row["timestamp"]))
    model_path = DATA_DIR / "population_model.joblib"
    # Only load the local artifact produced by this repository's evaluation script.
    bundle = joblib.load(model_path) if model_path.exists() else None
    return {"patients": patients, "observations": observations, "bundle": bundle}


def build_snapshot(profile: dict, records: list[dict], cursor: int = 0, scenario: str = "recorded",
                   bundle: dict | None = None) -> dict:
    """Construct a snapshot entirely from records available at this cursor."""
    if not records:
        raise ValueError("Patient has no readable observations")
    cursor = min(max(0, cursor), len(records) - 1)
    prefix = records[:cursor + 1]
    now = prefix[-1]["timestamp"]
    available = prefix[:-3] if scenario == "sensor_gap" else prefix
    result = forecast_prefix(available, profile, bundle, current_time=now)
    parameters = (bundle or {}).get("twin_parameters")
    calibration = (bundle or {}).get("twin_calibration")
    stream = predict_stream(available, profile, pooled_parameters=parameters, interval_calibration=calibration)
    known = {parse_time(row["timestamp"]): row["glucose_mg_dl"] for row in available}
    history = []
    # Recompute past issuance using exactly that issuance prefix, never a later state.
    for entry in stream[-24:]:
        index = entry["index"]
        if not entry["forecasts"]:
            continue
        population = {point["horizon_minutes"]: point for point in population_forecasts(available[:index + 1], profile, bundle)}
        for point in entry["forecasts"]:
            target = parse_time(point["timestamp"])
            counterpart = population.get(point["horizon_minutes"])
            history.append({
                "issued_at": entry["timestamp"], "target_time": point["timestamp"],
                "horizon_minutes": point["horizon_minutes"], "twin": point["glucose_mg_dl"],
                "population": counterpart["glucose_mg_dl"] if counterpart else None,
                "actual": known.get(target) if target <= parse_time(now) else None,
            })
    alerts = []
    if result["quality"]["status"] == "ok" and available and available[-1]["glucose_mg_dl"] <= 180:
        crossing = next((point for point in result["forecasts"]["twin"] if point["glucose_mg_dl"] > 180), None)
        if crossing:
            alerts.append({
                "id": f"{profile['id']}:{now}:high_glucose", "type": "high_glucose",
                "message": f"Model estimates glucose above 180 mg/dL in {crossing['horizon_minutes']} minutes. Research warning only.",
                "horizon_minutes": crossing["horizon_minutes"], "predicted_crossing_at": crossing["timestamp"],
                "threshold": 180, "label": "Future high-glucose excursion (research label)",
            })
    return clean_json({
        "patient": profile, "cursor": cursor, "total_observations": len(records), "current_time": now,
        "observations": available, **result, "alerts": alerts, "forecast_history": history, "scenario": scenario,
        "playback": {"kind": "recorded", "sampling_minutes": 15, "cursor_is_zero_based": True,
                     "hidden_observations": 3 if scenario == "sensor_gap" else 0},
    })


@app.get("/api/health")
def health():
    store = data_store()
    return success({"status": "ok", "dataset_ready": bool(store["patients"]), "population_model_ready": bool(store["bundle"]),
                    "mode": "recorded_research_prototype"})


@app.get("/api/patients")
def patients():
    return success(data_store()["patients"])


@app.get("/api/replay/{patient_id}")
def replay(patient_id: str, cursor: int = Query(default=0, ge=0), scenario: str = "recorded"):
    if scenario not in {"recorded", "sensor_gap"}:
        return JSONResponse(status_code=422, content={"error": "Scenario must be recorded or sensor_gap."})
    store = data_store()
    profile = next((patient for patient in store["patients"] if str(patient["id"]) == patient_id), None)
    if profile is None:
        return JSONResponse(status_code=404, content={"error": "Unknown patient."})
    records = store["observations"].get(patient_id, [])
    if not records:
        return JSONResponse(status_code=503, content={"error": "Patient observations are unavailable. Run data preparation."})
    return success(build_snapshot(profile, records, cursor, scenario, store["bundle"]))


@app.get("/api/benchmarks")
def benchmarks():
    benchmark = read_json("benchmark.json")
    if benchmark is None:
        return JSONResponse(status_code=503, content={"error": "Evaluation has not been run. Run scripts/evaluate.py."})
    return success(benchmark)


@app.get("/api/provenance")
def provenance():
    manifest = read_json("manifest.json")
    if manifest is None:
        return JSONResponse(status_code=503, content={"error": "Dataset has not been prepared. Run scripts/prepare_data.py."})
    return success(manifest)
