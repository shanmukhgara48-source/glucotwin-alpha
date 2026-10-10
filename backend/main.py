"""Persistent research care platform with recorded and synthetic arrival modes."""
from __future__ import annotations

import csv
import json
import math
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.twin import forecast_prefix, parse_time, population_forecasts, predict_stream
from backend.auth import bootstrap, clinic_user, router as auth_router
from backend.clinic import clinic_patients, router as clinic_router, snapshot_for
from backend.platform import initialize_platform, router as platform_router
from backend.operational import router as operational_router
from backend.worker import ForecastWorker

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("GLUCOTWIN_DATA_DIR", APP_ROOT / "data" / "processed"))
@asynccontextmanager
async def clinic_lifespan(app: FastAPI):
    if os.environ.get("GLUCOTWIN_ENV", "research") != "research":
        raise RuntimeError("Only the anonymized/synthetic research release is enabled. Private clinical service requires the source and clinical release gates.")
    bootstrap()
    initialize_platform()
    worker = ForecastWorker()
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="GlucoTwin", version="0.3.0", description="Arrival-aware care platform research release; clinic source and clinical validation pending.", lifespan=clinic_lifespan)
app.include_router(auth_router)
app.include_router(clinic_router)
app.include_router(platform_router)
app.include_router(operational_router)
FRONTEND_DIST = APP_ROOT / "frontend" / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend():
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(status_code=503, content={"error": "Frontend not built. Run npm run build in frontend or use Vite locally."})
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


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
                   bundle: dict | None = None, current_time: str | None = None) -> dict:
    """Construct a snapshot entirely from records available at this cursor."""
    if not records:
        raise ValueError("Patient has no readable observations")
    cursor = min(max(0, cursor), len(records) - 1)
    prefix = records[:cursor + 1]
    now = current_time or prefix[-1]["timestamp"]
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
        from backend.hybrid import context_at
        historical_profile = context_at(profile, entry["timestamp"])
        population = {point["horizon_minutes"]: point for point in population_forecasts(available[:index + 1], historical_profile, bundle)}
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
        crossing = next((point for point in result["forecasts"]["twin"] if point["horizon_minutes"] == 30 and point["glucose_mg_dl"] > 180), None)
        if crossing:
            alerts.append({
                "id": f"{profile['id']}:{now}:high_glucose", "type": "high_glucose",
                "message": f"Model estimates glucose above 180 mg/dL in {crossing['horizon_minutes']} minutes. Research warning only.",
                "horizon_minutes": crossing["horizon_minutes"], "predicted_crossing_at": crossing["timestamp"],
                "threshold": 180, "label": "Future high-glucose excursion (research label)",
            })
    snapshot = {
        "patient": profile, "cursor": cursor, "total_observations": len(records), "current_time": now,
        "observations": available, **result, "alerts": alerts, "forecast_history": history, "scenario": scenario,
        "playback": {"kind": "recorded", "sampling_minutes": 15, "cursor_is_zero_based": True,
                     "hidden_observations": 3 if scenario == "sensor_gap" else 0},
    }
    try:
        from backend.hybrid import clinic_forecast, load_clinic_bundle
        hybrid_bundle = load_clinic_bundle(DATA_DIR / "clinic_model.joblib")
        snapshot["clinic_model"] = clinic_forecast(available, profile, current_time=now, bundle=hybrid_bundle)
        event_risks = snapshot["clinic_model"].get("event_risks", [])
        if snapshot["clinic_model"] is not None:
            snapshot["alerts"] = [{"id": f"{profile['id']}:{now}:excursion:{risk['horizon_minutes']}",
                "type": "predicted_excursion", "horizon_minutes": risk["horizon_minutes"],
                "probability": risk["probability"], "threshold": risk["threshold"],
                "message": f"Excursion classifier exceeds its validation operating threshold within {risk['horizon_minutes']} minutes. Research warning only."}
                for risk in event_risks if risk["horizon_minutes"] == 30 and risk.get("event_eligible") and risk.get("exceeds_threshold")]
    except ImportError:
        snapshot["clinic_model"] = None
    return clean_json(snapshot)


@app.get("/api/health")
def health():
    store = data_store()
    return success({"status": "ok", "dataset_ready": bool(store["patients"]), "population_model_ready": bool(store["bundle"]),
                    "mode": "recorded_research_prototype"})


@app.get("/api/patients")
def patients(user: dict = Depends(clinic_user)):
    return success(clinic_patients(user))


@app.get("/api/replay/{patient_id}")
def replay(patient_id: str, cursor: int = Query(default=0, ge=0), scenario: str = "recorded",
           current_time: str | None = None, user: dict = Depends(clinic_user)):
    if scenario not in {"recorded", "sensor_gap"}:
        return JSONResponse(status_code=422, content={"error": "Scenario must be recorded or sensor_gap."})
    return success(snapshot_for(patient_id, user, cursor, scenario, current_time))


@app.get("/api/benchmarks")
def benchmarks(user: dict = Depends(clinic_user)):
    benchmark = read_json("benchmark.json")
    if benchmark is None:
        return JSONResponse(status_code=503, content={"error": "Evaluation has not been run. Run scripts/evaluate.py."})
    return success(benchmark)


@app.get("/api/provenance")
def provenance(user: dict = Depends(clinic_user)):
    manifest = read_json("manifest.json")
    if manifest is None:
        return JSONResponse(status_code=503, content={"error": "Dataset has not been prepared. Run scripts/prepare_data.py."})
    return success(manifest)


@app.get("/api/clinic-benchmark")
def clinic_benchmark(user: dict = Depends(clinic_user)):
    benchmark = read_json("clinic_benchmark.json")
    if benchmark is None:
        return JSONResponse(status_code=503, content={"error": "Clinic model evaluation has not been run."})
    return success(benchmark)


@app.get("/{path:path}", include_in_schema=False)
def frontend_route(path: str):
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"error": "API route not found."})
    candidate = (FRONTEND_DIST / path).resolve()
    if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate, headers={"Cache-Control": "no-store"})
    return frontend()
