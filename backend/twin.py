"""Causal damped-trend Kalman glucose twin, with transparent online adaptation.

The model is an engineering forecasting approximation, not a physiological or
clinically validated simulator. No function reads observations after its prefix.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import cos, pi, sin, sqrt
from typing import Any, Iterable

import numpy as np

FEATURE_NAMES = [
    "glucose_now", "lag_15", "lag_30", "lag_60", "trend_15", "trend_60",
    "mean_60", "std_60", "hour_sin", "hour_cos", "age", "bmi",
    "diabetes_duration_years", "sex_female",
]
HORIZONS = (30, 60)
DEFAULT_PARAMETERS = {"damping": 0.75, "process_sd": 4.0, "measurement_sd": 8.0}
NOMINAL_COVERAGE = 0.90


def parse_time(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _value(row: dict) -> float:
    return float(row["glucose_mg_dl"])


def observation_quality(observations: list[dict], current_time: str | datetime | None = None) -> dict:
    if not observations:
        return {"status": "warming_up", "message": "Waiting for five native readings.", "last_reading_at": None, "minutes_since_reading": None}
    last = parse_time(observations[-1]["timestamp"])
    now = parse_time(current_time) if current_time is not None else last
    age = max(0.0, (now - last).total_seconds() / 60)
    common = {"last_reading_at": last.isoformat(), "minutes_since_reading": round(age, 1)}
    if age > 20:
        return {**common, "status": "gap", "message": f"Latest reading is {age:.0f} minutes old. Forecasts are paused."}
    if len(observations) < 5:
        return {**common, "status": "warming_up", "message": "Collecting five native readings (60 minutes of history)."}
    times = [parse_time(row["timestamp"]) for row in observations[-5:]]
    if any(not 13 <= (b - a).total_seconds() / 60 <= 17 for a, b in zip(times, times[1:])):
        return {**common, "status": "gap", "message": "Recent readings contain a sensor gap. Waiting for five consecutive readings."}
    return {**common, "status": "ok", "message": "Native 15-minute recorded readings; future observations remain hidden."}


def extract_features(observations: list[dict], profile: dict | None = None) -> np.ndarray:
    """Fourteen causal features; requires five consecutive native observations."""
    if observation_quality(observations)["status"] != "ok":
        raise ValueError("Five consecutive native readings are required")
    profile = profile or {}
    values = np.asarray([_value(row) for row in observations[-5:]], dtype=float)
    now = parse_time(observations[-1]["timestamp"])
    hour = now.hour + now.minute / 60
    sex = str(profile.get("sex", "")).lower()
    sex_female = 1.0 if sex in {"female", "f", "woman", "女"} else (0.0 if sex in {"male", "m", "man", "男"} else np.nan)
    def context(key: str) -> float:
        value = profile.get(key)
        try:
            return float(value) if value is not None else np.nan
        except (TypeError, ValueError):
            return np.nan
    return np.asarray([
        values[-1], values[-2], values[-3], values[0], values[-1] - values[-2],
        values[-1] - values[0], values.mean(), values.std(), sin(2 * pi * hour / 24),
        cos(2 * pi * hour / 24), context("age"), context("bmi"),
        context("diabetes_duration_years"), sex_female,
    ], dtype=float)


def estimate_pooled_parameters(recordings: Iterable[list[dict]]) -> dict:
    """Fit a shared damped-trend prior using training patients only."""
    previous, current = [], []
    for observations in recordings:
        last_delta = None
        for before, after in zip(observations, observations[1:]):
            minutes = (parse_time(after["timestamp"]) - parse_time(before["timestamp"])).total_seconds() / 60
            if not 13 <= minutes <= 17:
                last_delta = None
                continue
            delta = _value(after) - _value(before)
            if last_delta is not None:
                previous.append(last_delta)
                current.append(delta)
            last_delta = delta
    if not previous:
        return DEFAULT_PARAMETERS.copy()
    a, b = np.asarray(previous), np.asarray(current)
    damping = float(np.clip(np.dot(a, b) / (np.dot(a, a) + 1e-6), 0.1, 0.98))
    residual_sd = float(np.std(b - damping * a))
    # Adjacent differences include sensor noise; cap process noise for stability.
    process_sd = float(np.clip(residual_sd / 2, 2, 15))
    return {"damping": damping, "process_sd": process_sd, "measurement_sd": 8.0}


class TwinFilter:
    """An independent patient state. Call update only with available readings."""
    def __init__(self, adapt: bool = True, pooled_parameters: dict | None = None):
        self.adapt = adapt
        self.prior = {**DEFAULT_PARAMETERS, **(pooled_parameters or {})}
        self.damping = float(self.prior["damping"])
        self.process_sd = float(self.prior["process_sd"])
        self.measurement_sd = float(self.prior["measurement_sd"])
        self.x: np.ndarray | None = None
        self.p = np.diag([self.measurement_sd ** 2, 25.0])
        self.timestamp: datetime | None = None
        self.last_glucose: float | None = None
        self.last_delta: float | None = None
        self.updates = 0
        self.adaptation_samples = 0
        self.sum_xx = 24 * 225.0
        self.sum_xy = self.sum_xx * self.damping
        self.sum_residual_sq = 24 * (2 * self.process_sd) ** 2
        self.last_update: dict = {}

    def _transition(self, steps: float = 1) -> np.ndarray:
        retention = self.damping ** steps
        displacement = self.damping * (1 - retention) / max(1 - self.damping, 1e-8)
        return np.asarray([[1.0, displacement], [0.0, retention]])

    def _process_covariance(self, steps: float = 1) -> np.ndarray:
        return np.diag([(self.process_sd * 0.5) ** 2, self.process_sd ** 2]) * max(steps, 0.01)

    def update(self, glucose: float, timestamp: str | datetime) -> dict:
        glucose, time = float(glucose), parse_time(timestamp)
        if not np.isfinite(glucose):
            raise ValueError("Glucose must be finite")
        if self.timestamp is not None and time <= self.timestamp:
            raise ValueError("Readings must have strictly increasing timestamps")
        if self.x is None:
            self.x = np.asarray([glucose, 0.0])
            prediction, innovation, gain = glucose, 0.0, 1.0
        else:
            minutes = (time - self.timestamp).total_seconds() / 60
            steps = minutes / 15
            if minutes > 45:
                # A long gap resets stale trend; previous observations are not imputed.
                self.x[1] = 0
                self.p += np.diag([100.0, 25.0])
                self.last_delta = None
            transition = self._transition(steps)
            prior_x = transition @ self.x
            prior_p = transition @ self.p @ transition.T + self._process_covariance(steps)
            prediction = float(prior_x[0])
            innovation = glucose - prediction
            k = prior_p[:, 0] / (prior_p[0, 0] + self.measurement_sd ** 2)
            self.x = prior_x + k * innovation
            self.p = (np.eye(2) - np.outer(k, [1.0, 0.0])) @ prior_p
            self.p = (self.p + self.p.T) / 2
            gain = float(k[0])
            delta = glucose - float(self.last_glucose)
            if 13 <= minutes <= 17 and self.last_delta is not None:
                self.adaptation_samples += 1
                if self.adapt:
                    # Shrink patient estimates toward the training-cohort prior.
                    clipped_delta = float(np.clip(delta, -100, 100))
                    clipped_previous = float(np.clip(self.last_delta, -100, 100))
                    self.sum_xx += clipped_previous ** 2
                    self.sum_xy += clipped_previous * clipped_delta
                    self.damping = float(np.clip(self.sum_xy / self.sum_xx, 0.1, 0.98))
                    residual = clipped_delta - self.damping * clipped_previous
                    self.sum_residual_sq += residual ** 2
                    self.process_sd = float(np.clip(sqrt(self.sum_residual_sq / (24 + self.adaptation_samples)) / 2, 2, 15))
            self.last_delta = delta if 13 <= minutes <= 17 else None
        self.timestamp, self.last_glucose = time, glucose
        self.updates += 1
        self.last_update = {
            "timestamp": time.isoformat(), "observed": glucose,
            "predicted_before_update": prediction, "innovation": innovation, "gain": gain,
            "level": float(self.x[0]), "trend": float(self.x[1]),
            "damping": self.damping, "process_sd": self.process_sd,
        }
        return self.last_update.copy()

    def predict(self, horizon_minutes: int, calibration: dict | None = None) -> dict:
        if self.x is None or self.timestamp is None:
            raise ValueError("Update the filter before predicting")
        x, p = self.x.copy(), self.p.copy()
        # Propagate each native step so process uncertainty accumulates correctly.
        for _ in range(horizon_minutes // 15):
            transition = self._transition()
            x = transition @ x
            p = transition @ p @ transition.T + self._process_covariance()
        center = float(x[0])
        model_half_width = 1.6448536269514722 * sqrt(max(0.0, p[0, 0]) + self.measurement_sd ** 2)
        calibrated = (calibration or {}).get(horizon_minutes, (calibration or {}).get(str(horizon_minutes), {}))
        # Empirical held-out residual width is a fixed validation-calibrated interval.
        half_width = float(calibrated.get("residual_quantile", model_half_width))
        return {
            "timestamp": (self.timestamp + timedelta(minutes=horizon_minutes)).isoformat(),
            "horizon_minutes": horizon_minutes, "glucose_mg_dl": center,
            "lower": max(0.0, center - half_width), "upper": center + half_width,
            "interval_method": "validation_residual_quantile" if calibrated else "uncalibrated_gaussian_state_model",
            "nominal_coverage": NOMINAL_COVERAGE,
        }

    def state(self) -> dict:
        return {
            "level": float(self.x[0]) if self.x is not None else None,
            "trend": float(self.x[1]) if self.x is not None else None,
            "innovation": self.last_update.get("innovation", 0), "updates": self.updates,
            "adaptation_samples": self.adaptation_samples if self.adapt else 0,
            "uncertainty": sqrt(max(0, float(self.p[0, 0]))),
            "parameters": {"damping": self.damping, "process_sd": self.process_sd, "measurement_sd": self.measurement_sd},
            "pooled_parameters": self.prior.copy(),
            "personalized": self.adapt,
        }


def predict_stream(observations: list[dict], profile: dict | None = None, adapt: bool = True,
                   pooled_parameters: dict | None = None, interval_calibration: dict | None = None) -> list[dict]:
    """One-pass filter predictions for evaluation; each entry sees only its prefix."""
    twin = TwinFilter(adapt=adapt, pooled_parameters=pooled_parameters)
    output = []
    for index, row in enumerate(observations):
        update = twin.update(_value(row), row["timestamp"])
        quality = observation_quality(observations[max(0, index - 4): index + 1])
        output.append({
            "index": index, "timestamp": row["timestamp"], "state": twin.state(), "update": update,
            "quality": quality, "forecasts": [twin.predict(h, interval_calibration) for h in HORIZONS] if quality["status"] == "ok" else [],
        })
    return output


def population_forecasts(observations: list[dict], profile: dict, bundle: dict | None) -> list[dict]:
    if not bundle or not bundle.get("models") or observation_quality(observations)["status"] != "ok":
        return []
    features = extract_features(observations, profile).reshape(1, -1)
    now = parse_time(observations[-1]["timestamp"])
    output = []
    for horizon in HORIZONS:
        model = bundle["models"].get(horizon, bundle["models"].get(str(horizon)))
        if model is None:
            continue
        prediction = float(model.predict(features)[0])
        calibration = bundle.get("calibration", {}).get(horizon, bundle.get("calibration", {}).get(str(horizon), {}))
        width = calibration.get("residual_quantile")
        output.append({
            "timestamp": (now + timedelta(minutes=horizon)).isoformat(), "horizon_minutes": horizon,
            "glucose_mg_dl": prediction, "lower": max(0, prediction - float(width)) if width is not None else None,
            "upper": prediction + float(width) if width is not None else None,
            "interval_method": "validation_residual_quantile" if width is not None else "unavailable",
            "nominal_coverage": NOMINAL_COVERAGE,
        })
    return output


def forecast_prefix(observations: list[dict], profile: dict | None = None, population_bundle: dict | None = None,
                    adapt: bool = True, pooled_parameters: dict | None = None,
                    interval_calibration: dict | None = None, current_time: str | datetime | None = None) -> dict:
    """Pure forecasting interface: no shared state, only caller-provided past rows."""
    profile, bundle = profile or {}, population_bundle or {}
    parameters = pooled_parameters or bundle.get("twin_parameters")
    calibration = interval_calibration or bundle.get("twin_calibration", {})
    stream = predict_stream(observations, profile, adapt, parameters, calibration)
    quality = observation_quality(observations, current_time)
    return {
        "forecasts": {"twin": stream[-1]["forecasts"] if stream and quality["status"] == "ok" else [],
                      "population": population_forecasts(observations, profile, bundle) if quality["status"] == "ok" else []},
        "state": stream[-1]["state"] if stream else TwinFilter(adapt, parameters).state(),
        "quality": quality,
        "update_history": [row["update"] for row in stream[-32:]],
        "intervals": {"nominal_coverage": NOMINAL_COVERAGE, "twin_calibrated": bool(calibration),
                      "population_calibrated": bool(bundle.get("calibration")),
                      "message": "Coverage is measured on held-out patients; individual predictions are research estimates." if calibration else "Twin intervals are Gaussian model estimates; empirical calibration is unavailable."},
    }
