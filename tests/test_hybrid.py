"""Focused safety tests for matured adaptation and time-of-availability behavior."""
from datetime import datetime, timedelta

import numpy as np

from backend.hybrid import ADAPTATION, causal_corrections, clinic_forecast, context_at


class OffsetModel:
    def __init__(self, offset=5): self.offset=offset
    def predict(self, x):
        return x[:,0]+self.offset+np.nan_to_num(x[:,10],nan=0)*.01


class RiskModel:
    def predict_proba(self,x): return np.tile([.1,.9],(len(x),1))


def readings(count=20):
    start=datetime(2026,1,1,9)
    return [{"timestamp":(start+timedelta(minutes=i*15)).isoformat(),"glucose_mg_dl":100+i*5.0} for i in range(count)]


def bundle():
    return {"models":{30:OffsetModel(),60:OffsetModel()},"classifiers":{30:RiskModel(),60:RiskModel()},
            "probability_calibrators":{},"intervals":{"population":{30:10.,60:15.},"hybrid":{30:10.,60:15.}},
            "alert_thresholds":{30:.7,60:.8},"adaptation":ADAPTATION,
            "metadata":{"version":"test","primary":"population","personalization_status":"experimental"}}


def test_updates_wait_for_matured_earlier_targets():
    early=clinic_forecast(readings(6),{},bundle=bundle())
    mature=clinic_forecast(readings(7),{},bundle=bundle())
    assert early["adaptation"]["matured_samples"]==0
    assert early["adaptation"]["correction_mg_dl"]==0
    assert mature["adaptation"]["matured_samples"]==1
    assert mature["adaptation"]["correction_mg_dl"]>0
    update=mature["adaptation"]["history"][0]
    assert datetime.fromisoformat(update["timestamp"])-datetime.fromisoformat(update["forecast_issued_at"])==timedelta(minutes=30)


def test_future_records_do_not_change_prefix_forecast():
    original=readings()
    cutoff=original[9]["timestamp"]
    before=clinic_forecast(original,{"age":50},current_time=cutoff,bundle=bundle())
    changed=[dict(row) for row in original]
    for row in changed[10:]: row["glucose_mg_dl"]=9999
    assert clinic_forecast(changed,{"age":50},current_time=cutoff,bundle=bundle())==before


def test_late_context_does_not_rewrite_old_forecasts():
    obs=readings(12)
    profile={"baseline_context":{"age":50},"context_entries":[{"kind":"historical","value":{"age":90},
        "observed_at":obs[0]["timestamp"],"available_at":obs[8]["timestamp"]}]}
    snapshot=clinic_forecast(obs,profile,bundle=bundle())
    old=next(row for row in snapshot["forecast_history"] if row["issued_at"]==obs[4]["timestamp"] and row["horizon_minutes"]==30)
    assert old["population_mg_dl"]==125.5
    newer=next(row for row in snapshot["forecast_history"] if row["issued_at"]==obs[8]["timestamp"] and row["horizon_minutes"]==30)
    assert newer["population_mg_dl"]==145.9
    assert context_at(profile,obs[4]["timestamp"])["age"]==50


def test_late_reading_cannot_enter_an_earlier_issue():
    obs=readings(12)
    obs[2]["available_at"]=obs[8]["timestamp"]
    snapshot=clinic_forecast(obs,{},bundle=bundle())
    assert not any(row["issued_at"]==obs[4]["timestamp"] for row in snapshot["forecast_history"])
    assert any(row["issued_at"]==obs[8]["timestamp"] for row in snapshot["forecast_history"])


def test_gap_suppresses_forecasts_and_event_warnings():
    obs=readings(10)
    later=(datetime.fromisoformat(obs[-1]["timestamp"])+timedelta(minutes=45)).isoformat()
    snapshot=clinic_forecast(obs,{},current_time=later,bundle=bundle())
    assert snapshot["quality"]["status"]=="gap"
    assert snapshot["forecasts"]=={"population":[],"hybrid":[]}
    assert snapshot["event_risks"]==[]


def test_ongoing_high_is_not_an_advance_excursion_alert():
    snapshot=clinic_forecast(readings(20),{},bundle=bundle())
    for risk in snapshot["event_risks"]:
        assert risk["ongoing_high"]
        assert not risk["exceeds_threshold"]
        assert not risk["event_eligible"]


def test_correction_is_bounded_and_patient_independent():
    obs=readings(100)
    origins=[{"timestamp":row["timestamp"]} for row in obs]
    corrections,states=causal_corrections(origins,np.zeros(len(origins)),obs,30)
    assert np.max(corrections)<=ADAPTATION["max_correction"]
    assert states[-1]["matured_samples"]==98
    first=clinic_forecast(readings(7),{"age":20},bundle=bundle())
    clinic_forecast(readings(50),{"age":90},bundle=bundle())
    assert clinic_forecast(readings(7),{"age":20},bundle=bundle())==first


def test_known_patient_uses_their_evaluation_fold():
    b=bundle()
    other=bundle();other["models"]={30:OffsetModel(20),60:OffsetModel(20)};other["metadata"]["version"]="fold2"
    b["patient_folds"]={"p2":2};b["fold_bundles"]={2:other}
    snapshot=clinic_forecast(readings(8),{"id":"p2"},bundle=b)
    assert snapshot["model"]["version"]=="fold2"


def test_aware_context_compares_with_naive_recorded_clock():
    obs=readings(12)
    profile={"baseline_context":{"age":50},"context_entries":[{"kind":"historical","value":{"age":90},
        "observed_at":obs[0]["timestamp"]+"Z","available_at":obs[8]["timestamp"]+"Z"}]}
    snapshot=clinic_forecast(obs,profile,current_time=obs[-1]["timestamp"]+"Z",bundle=bundle())
    assert snapshot["quality"]["status"]=="ok"
    assert snapshot["adaptation"]["matured_samples"]>0


def test_duplicate_readings_do_not_double_adaptation():
    obs=readings(12)
    duplicate=obs[:6]+[dict(obs[5])]+obs[6:]
    assert clinic_forecast(duplicate,{},bundle=bundle())==clinic_forecast(obs,{},bundle=bundle())


def test_missing_target_is_never_imputed_for_residual_updates():
    obs=readings(8)
    origins=[{"timestamp":obs[4]["timestamp"]}]
    # A forecast at index4 targets index6, which is absent; index7 cannot stand in.
    missing=obs[:6]+obs[7:]
    correction,states=causal_corrections(origins,np.asarray([125.]),missing,30)
    assert correction.tolist()==[0.]
    assert states[-1]["matured_samples"]==0


def test_frozen_patient_folds_and_saved_primary_gate():
    import json
    from pathlib import Path
    from backend.hybrid import load_clinic_bundle
    directory=Path(__file__).resolve().parents[1]/"data/processed"
    protocol=json.loads((directory/"evaluation_protocol.json").read_text())
    evaluated=[]
    for fold in protocol["outer_folds"]:
        train,cal,test=map(set,[fold["training"],fold["calibration"],fold["evaluation"]])
        assert not (train & cal or train & test or cal & test)
        assert len(train|cal|test)==100
        evaluated.extend(test)
    assert len(set(evaluated))==len(evaluated)==100
    saved=load_clinic_bundle()
    gate=saved["metadata"]["primary_gate"]
    assert saved["metadata"]["primary"]==("hybrid" if gate["mae_difference_ci"][1]<0 else "population")
    for patient,fold in saved["patient_folds"].items():
        selected=saved["fold_bundles"].get(fold,saved)
        assert patient not in selected["training_patient_ids"]
        assert patient not in selected["calibration_patient_ids"]
        assert patient in selected["evaluation_patient_ids"]


def test_late_target_matures_only_after_actual_arrival():
    obs=readings(10)
    obs[6]["available_at"]=obs[9]["timestamp"]
    origins=[{"timestamp":obs[i]["timestamp"]} for i in [4,8,9]]
    correction,states=causal_corrections(origins,np.asarray([125.,140.,145.]),obs,30)
    assert states[1]["matured_samples"]==0
    assert correction[1]==0
    assert states[2]["matured_samples"]==1
    assert states[2]["history"][0]["timestamp"]==obs[9]["timestamp"]
    assert states[2]["history"][0]["observed_at"]==obs[6]["timestamp"]
