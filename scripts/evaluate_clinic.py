"""Frozen five-fold grouped internal retrospective clinic benchmark.

Separate training, parameter-selection, calibration and test patients. A new
external/prospective cohort is still needed: this public cohort was inspected.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, KFold
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.hybrid import ADAPTATION, calibrated_probabilities, causal_corrections
from backend.twin import FEATURE_NAMES, HORIZONS
from scripts.evaluate import load_recordings

OUT = ROOT / "data/processed"
SEED = 20261010
PARAMETERS = [
    {"max_leaf_nodes": 15, "learning_rate": .08, "l2_regularization": 10.0, "min_samples_leaf": 50},
    {"max_leaf_nodes": 7, "learning_rate": .08, "l2_regularization": 20.0, "min_samples_leaf": 75},
]


def make_examples(recording):
    obs = recording["observations"]
    times = np.asarray([np.datetime64(row["timestamp"], 'm') for row in obs])
    values = np.asarray([row["glucose_mg_dl"] for row in obs])
    profile = recording["profile"]
    context = [profile.get("age", np.nan), profile.get("bmi", np.nan), profile.get("diabetes_duration_years", np.nan),
               1.0 if str(profile.get("sex", "")).lower() in ["female", "f", "女"] else 0.0]
    output = {h: [] for h in HORIZONS}
    for index in range(4, len(obs)):
        if np.any(np.diff(times[index - 4:index + 1]).astype('timedelta64[m]').astype(int) != 15):
            continue
        v = values[index - 4:index + 1]
        now = datetime.fromisoformat(obs[index]["timestamp"])
        hour = now.hour + now.minute / 60
        features = np.asarray([v[-1],v[-2],v[-3],v[0],v[-1]-v[-2],v[-1]-v[0],v.mean(),v.std(),
                               np.sin(2*np.pi*hour/24),np.cos(2*np.pi*hour/24),*context], dtype=float)
        for horizon in HORIZONS:
            steps = horizon // 15
            if index + steps >= len(obs) or np.any(np.diff(times[index:index + steps + 1]).astype('timedelta64[m]').astype(int) != 15):
                continue
            future = values[index + 1:index + steps + 1]
            crossing = np.flatnonzero(future > 180)
            event = bool(values[index] <= 180 and crossing.size)
            event_at = (now + timedelta(minutes=int((crossing[0]+1)*15))).isoformat() if event else None
            output[horizon].append({"patient_id": recording["patient_id"], "recording_id": recording["recording_id"],
                "index": index, "timestamp": now.isoformat(), "features": features, "current": float(v[-1]),
                "actual": float(future[-1]), "event_eligible": bool(v[-1] <= 180), "event": event,
                "event_at": event_at, "phase": "cold_start" if (times[index]-times[0]).astype('timedelta64[m]').astype(int)<1440 else "adapted",
                "linear_trend": float(v.mean() + np.dot(np.arange(-2,3),v-v.mean())/10*(2+horizon/15))})
    return output


def stacked(rows):
    return np.vstack([r["features"] for r in rows]), np.asarray([r["actual"] for r in rows])


def regressor(parameters, iterations):
    return HistGradientBoostingRegressor(**parameters, max_iter=iterations, early_stopping=False, random_state=SEED)


def train(rows_by_h, parameters, iterations):
    models, ablations, classifiers = {}, {}, {}
    for h in HORIZONS:
        rows = rows_by_h[h]
        x,y = stacked(rows)
        models[h] = regressor(parameters, iterations).fit(x,y)
        no_context = x.copy(); no_context[:,10:] = 0
        ablations[h] = regressor(parameters, iterations).fit(no_context,y)
        eligible = [r for r in rows if r["event_eligible"]]
        event_x,_ = stacked(eligible)
        event_y = np.asarray([r["event"] for r in eligible], dtype=int)
        classifiers[h] = HistGradientBoostingClassifier(**parameters, max_iter=iterations,
            early_stopping=False, random_state=SEED).fit(event_x,event_y)
    return models, ablations, classifiers


def past_valid_origins(recording):
    """Origins selected solely from historical quality, irrespective of future labels."""
    from backend.twin import observation_quality, extract_features
    origins=[]
    observations=recording["observations"]
    for index in range(4,len(observations)):
        prefix=observations[index-4:index+1]
        if observation_quality(prefix)["status"]=="ok":
            origins.append({"index":index,"timestamp":observations[index]["timestamp"],
                            "features":extract_features(prefix,recording["profile"])})
    return origins


def predict(recordings, by_record, models, ablations, classifiers, fold):
    output = {h: [] for h in HORIZONS}
    for recording in recordings:
        origins=past_valid_origins(recording)
        if not origins: continue
        x=np.vstack([row["features"] for row in origins])
        location={row["index"]:i for i,row in enumerate(origins)}
        for h in HORIZONS:
            rows = by_record[recording["recording_id"]][h]
            if not rows: continue
            # Issue every past-valid forecast; future label eligibility only selects scoring rows.
            population = models[h].predict(x)
            correction, states = causal_corrections(origins, population, recording["observations"],h)
            x_nc = x.copy(); x_nc[:,10:] = 0
            no_context = ablations[h].predict(x_nc)
            probabilities = classifiers[h].predict_proba(x)[:,1]
            for row in rows:
                i=location[row["index"]]
                base,adjustment,nc,prob=population[i],correction[i],no_context[i],probabilities[i]
                metadata = {key:value for key,value in row.items() if key != "features"}
                output[h].append({**metadata,"population":float(base),"hybrid":float(base+adjustment),
                    "population_no_context":float(nc),"persistence":row["current"],"raw_probability":float(prob),
                    "correction":float(adjustment),"matured_samples":states[i]["matured_samples"],"fold":fold})
    return output


def episode_metrics(rows, threshold):
    eligible = sorted([r for r in rows if r["event_eligible"]], key=lambda r:(r["recording_id"],r["timestamp"]))
    horizon = rows[0]["horizon_minutes"] if rows else 30
    reachable = {(r["recording_id"],r["event_at"]) for r in eligible if r["event"]}
    last_alert = {}
    alerts, matched, leads = [],set(),[]
    tp_windows=fp_windows=fn_windows=0
    for r in eligible:
        alert = r["probability"] >= threshold
        tp_windows += int(alert and r["event"]); fp_windows += int(alert and not r["event"]); fn_windows += int(not alert and r["event"])
        if not alert: continue
        stamp = datetime.fromisoformat(r["timestamp"])
        previous = last_alert.get(r["recording_id"])
        if previous is not None and (stamp-previous).total_seconds()/60 < horizon: continue
        last_alert[r["recording_id"]] = stamp
        alerts.append(bool(r["event"]))
        if r["event"]:
            key = (r["recording_id"],r["event_at"])
            if key not in matched:
                matched.add(key); leads.append((datetime.fromisoformat(r["event_at"])-stamp).total_seconds()/60)
    false = len(alerts)-sum(alerts)
    days = len(eligible)*15/1440
    return {"episode_precision":float(sum(alerts)/len(alerts)) if alerts else None,
        "episode_recall":float(len(matched)/len(reachable)) if reachable else None,
        "true_alert_episodes":int(sum(alerts)),"false_alert_episodes":int(false),"reachable_event_episodes":len(reachable),
        "matched_event_episodes":len(matched),"false_alerts_per_patient_day":float(false/days) if days else None,
        "eligible_patient_days":days,"warning_lead_time_minutes":float(np.median(leads)) if leads else None,
        "precision":float(tp_windows/(tp_windows+fp_windows)) if tp_windows+fp_windows else None,
        "recall":float(tp_windows/(tp_windows+fn_windows)) if tp_windows+fn_windows else None}


def calibrate(predictions):
    intervals, calibrators, thresholds, audits = {"population":{},"hybrid":{},"population_no_context":{},"persistence":{},"linear_trend":{}},{},{},{}
    for h,rows in predictions.items():
        for model in intervals:
            intervals[model][h] = float(np.quantile([abs(r[model]-r["actual"]) for r in rows],.9, method="higher"))
        eligible = [r for r in rows if r["event_eligible"]]
        p=np.clip([r["raw_probability"] for r in eligible],1e-6,1-1e-6)
        logits = np.log(p/(1-p)).reshape(-1,1)
        y=np.asarray([r["event"] for r in eligible],dtype=int)
        calibrator=LogisticRegression(C=1.0,random_state=SEED).fit(logits,y) if len(np.unique(y))>1 else None
        calibrators[h]=calibrator
        all_raw=np.clip([r["raw_probability"] for r in rows],1e-6,1-1e-6)
        all_logits=np.log(all_raw/(1-all_raw)).reshape(-1,1)
        calibrated=calibrator.predict_proba(all_logits)[:,1] if calibrator is not None else all_raw
        for r,pred in zip(rows,calibrated): r["probability"]=float(pred); r["horizon_minutes"]=h
        candidates=[]
        for threshold in [*np.arange(.02,1,.02),1.01]:
            metrics=episode_metrics(rows,float(threshold))
            if metrics["false_alerts_per_patient_day"] is not None and metrics["false_alerts_per_patient_day"]<=1:
                candidates.append((metrics["episode_recall"] or 0, metrics["episode_precision"] or 0, float(threshold),metrics))
        selected=max(candidates,key=lambda c:(c[0],c[1],-c[2]))
        thresholds[h]=selected[2]
        audits[h]={"selected_threshold":selected[2],"calibration_metrics":selected[3],"selection":"maximum reachable-event recall subject to <=1 false alert episode per24 eligible forecast hours; precision then lower threshold tie-break"}
    return intervals,calibrators,thresholds,audits


def apply_calibration(predictions, intervals, calibrators, thresholds):
    for h,rows in predictions.items():
        p=np.clip([r["raw_probability"] for r in rows],1e-6,1-1e-6)
        logits=np.log(p/(1-p)).reshape(-1,1)
        probabilities=calibrators[h].predict_proba(logits)[:,1] if calibrators[h] else p
        for r,prob in zip(rows,probabilities):
            r["probability"]=float(prob);r["horizon_minutes"]=h;r["alert_threshold"]=thresholds[h]
            r["widths"]={model:widths[h] for model,widths in intervals.items()}


def bootstrap_summary(rows, model, repetitions):
    sums=defaultdict(lambda:[0.,0])
    for row in rows:
        sums[row["patient_id"]][0]+=abs(row[model]-row["actual"]);sums[row["patient_id"]][1]+=1
    values=np.asarray(list(sums.values()))
    indices=np.random.default_rng(SEED).integers(0,len(values),(repetitions,len(values)))
    draws=values[indices,0].sum(axis=1)/values[indices,1].sum(axis=1)
    return [float(v) for v in np.quantile(draws,[.025,.975])]


def metrics(rows,model,horizon,phase,repetitions):
    selected=rows if phase=="all" else [r for r in rows if r["phase"]==phase]
    actual=np.asarray([r["actual"] for r in selected]);prediction=np.asarray([r[model] for r in selected])
    widths=np.asarray([r["widths"][model] for r in selected])
    eligible=[r for r in selected if r["event_eligible"]]
    brier=np.mean([(r["probability"]-int(r["event"]))**2 for r in eligible]) if eligible else None
    return {"model":model,"horizon_minutes":horizon,"phase":phase,"n_predictions":len(selected),
        "n_patients":len({r["patient_id"] for r in selected}),"mae":float(np.mean(abs(prediction-actual))),
        "rmse":float(np.sqrt(np.mean((prediction-actual)**2))),"mae_ci":bootstrap_summary(selected,model,repetitions),
        "interval_coverage":float(np.mean((actual>=np.maximum(0,prediction-widths))&(actual<=prediction+widths))),
        "interval_level":.9,"mean_interval_width":float(np.mean(2*widths)),"brier_score":float(brier) if brier is not None else None}


def observed_episode_audit(recordings):
    onsets=set();native=gap=prevalent=0
    for recording in recordings:
        obs=recording["observations"]
        prevalent+=bool(obs and obs[0]["glucose_mg_dl"]>180)
        for before,after in zip(obs,obs[1:]):
            if before["glucose_mg_dl"]<=180<after["glucose_mg_dl"]:
                onsets.add((recording["recording_id"],after["timestamp"]))
                minutes=(datetime.fromisoformat(after["timestamp"])-datetime.fromisoformat(before["timestamp"])).total_seconds()/60
                native+=minutes==15;gap+=minutes!=15
    return onsets,{"observed_event_episodes":len(onsets),"native_observed_event_episodes":native,
                   "gap_associated_observed_transitions":gap,"recordings_starting_already_high":prevalent,
                   "overall_recall_denominator":"All observed below/equal180 to above180 transitions, including warm-up/gap-unreachable onsets; recording-start prevalent high excluded because onset is unobserved."}


def event_fold_metrics(rows, recordings):
    # Each fold selected its own threshold on distinct calibration patients.
    totals=[]
    for fold in sorted({r["fold"] for r in rows}):
        selected=[r for r in rows if r["fold"]==fold]
        totals.append(episode_metrics(selected,selected[0]["alert_threshold"]))
    true=sum(r["true_alert_episodes"] for r in totals);false=sum(r["false_alert_episodes"] for r in totals)
    reachable=sum(r["reachable_event_episodes"] for r in totals);matched=sum(r["matched_event_episodes"] for r in totals)
    days=sum(r["eligible_patient_days"] for r in totals)
    observed,observed_audit=observed_episode_audit(recordings)
    reachable_keys={(row["recording_id"],row["event_at"]) for row in rows if row["event"]}
    return {**observed_audit,"overall_observed_episode_recall":matched/len(observed) if observed else None,
        "unreachable_event_episodes":len(observed-reachable_keys),"forecastable_event_fraction":len(reachable_keys & observed)/len(observed) if observed else None,
        "brier_score":float(np.mean([(row["probability"]-int(row["event"]))**2 for row in rows if row["event_eligible"]])),
        "probability_model":"separate boosted excursion classifier with calibration-only logistic adjustment",
        "episode_precision":true/(true+false) if true+false else None,"episode_recall":matched/reachable if reachable else None,
        "false_alerts_per_patient_day":false/days if days else None,"eligible_patient_days":days,
        "true_alert_episodes":true,"false_alert_episodes":false,"reachable_event_episodes":reachable,"matched_event_episodes":matched,
        "warning_lead_time_minutes":float(np.median([r["warning_lead_time_minutes"] for r in totals if r["warning_lead_time_minutes"] is not None]))}


def paired(rows, left, right, repetitions):
    sums=defaultdict(lambda:[0.,0])
    for row in rows:
        sums[row["patient_id"]][0]+=abs(row[left]-row["actual"])-abs(row[right]-row["actual"]);sums[row["patient_id"]][1]+=1
    values=np.asarray(list(sums.values()));indices=np.random.default_rng(SEED).integers(0,len(values),(repetitions,len(values)))
    draws=values[indices,0].sum(axis=1)/values[indices,1].sum(axis=1);ci=[float(v) for v in np.quantile(draws,[.025,.975])]
    return {"model":left,"reference":right,"horizon_minutes":rows[0]["horizon_minutes"],"mae_difference":float(values[:,0].sum()/values[:,1].sum()),
        "mae_difference_ci":ci,"bootstrap_unit":"patient","direction":"negative favors model","supported_improvement":bool(ci[1]<0),
        "inconclusive_at_95_percent":bool(ci[0]<=0<=ci[1])}


def inner_select(rows,iterations):
    x,y=stacked(rows);groups=np.asarray([r["patient_id"] for r in rows]);scores=[]
    for parameters in PARAMETERS:
        errors=[]
        for training,validation in GroupKFold(3).split(x,y,groups):
            model=regressor(parameters,iterations).fit(x[training],y[training]);pred=model.predict(x[validation])
            errors.append(float(np.mean(abs(pred-y[validation]))))
        scores.append({"parameters":parameters,"fold_mae":errors,"mean_mae":float(np.mean(errors))})
    return min(scores,key=lambda r:r["mean_mae"])["parameters"],scores


def freeze_protocol(recordings,iterations,bootstrap):
    ids=np.asarray(sorted({r["patient_id"] for r in recordings}));folds=[]
    for fold,(outertrain,test) in enumerate(KFold(5,shuffle=True,random_state=SEED).split(ids),1):
        pool=np.random.default_rng(SEED+fold).permutation(ids[outertrain]);ncal=max(1,int(len(pool)*.2))
        folds.append({"fold":fold,"training":sorted(pool[ncal:].tolist()),"calibration":sorted(pool[:ncal].tolist()),"evaluation":sorted(ids[test].tolist())})
    protocol={"status":"frozen_before_evaluation","frozen_at":datetime.now(timezone.utc).isoformat(),"seed":SEED,"outer_folds":folds,
        "design":"Five outer patient folds; three grouped inner folds select regression hyperparameters on30-minute training MAE;20% outer training patients are calibration-only.",
        "parameters":PARAMETERS,"max_iter":iterations,"bootstrap_repetitions":bootstrap,"bootstrap_unit":"patient",
        "primary_horizon_minutes":30,"secondary_horizon_minutes":60,"native_cadence_minutes":15,
        "target":"exact native endpoint CGM; event: current<=180 and any native future CGM>180 within horizon",
        "event_episode":"first above180 native reading reachable from a below/equal180 eligible forecast; alert cooldown equals horizon; one onset matched at most once",
        "alert_selection":"Calibration-only maximum episode recall constrained to<=1 false alert per24 eligible forecast hours; threshold grid .02:.02:.98 plus1.01(abstain)",
        "intervals":"Separate-patient90th percentile absolute residual, fixed empirical widths; no distribution-free claim",
        "probabilities":"Separate-patient logistic calibration of raw classifier logits, C=1.0",
        "adaptation":ADAPTATION,"primary_model_gate":"hybrid only if30-minute paired patient-bootstrap95% CI upper bound<0; otherwise population, adaptation experimental",
        "phase":"First24h of each recording cold_start; subsequent origins adapted. State resets per recording.",
        "context":"Matched age/sex/BMI/duration, assumed available at baseline; untimed labs/medications excluded",
        "evidence_boundary":"Internal retrospective validation: patients and legacy evaluation already inspected. No external/prospective/clinical validation."}
    frozen=OUT/"evaluation_protocol.json"
    if frozen.exists():
        previous=json.loads(frozen.read_text())
        if previous.get("max_iter")!=iterations or previous.get("bootstrap_repetitions")!=bootstrap:
            raise ValueError("Existing frozen protocol differs; preserve it and explicitly version a revised experiment")
        protocol=previous
    else: frozen.write_text(json.dumps(protocol,indent=2))
    return protocol


def select_demo(rows):
    primary={p["recording_id"] for p in json.loads((OUT/"patients.json").read_text())}
    def staffed(row):
        stamp=datetime.fromisoformat(row["timestamp"])
        return stamp.weekday()<5 and 9<=stamp.hour<17
    candidates=[r for r in rows if r["recording_id"] in primary and r["event"] and r["probability"]>=r["alert_threshold"]+.05
        and r["phase"]=="adapted" and staffed(r)
        and r["event_at"]==(datetime.fromisoformat(r["timestamp"])+timedelta(minutes=30)).isoformat()
        and abs(r["hybrid"]-r["actual"])<abs(r["population"]-r["actual"])]
    # Prefer the already selected demonstration model fold; this only curates display cases.
    preferred=[r for r in candidates if r["fold"]==4]
    candidates=preferred or candidates
    if not candidates: candidates=[r for r in rows if r["recording_id"] in primary and r["event"] and r["probability"]>=r["alert_threshold"] and staffed(r)]
    if not candidates: return {"available":False,"curation_note":"No true advance alert in the default staffed demonstration window."}
    r=min(candidates,key=lambda a:abs(a["hybrid"]-a["actual"]))
    stable=next((a for a in rows if a["recording_id"]==r["recording_id"] and a["phase"]=="adapted" and 90<a["current"]<145
                 and not a["event"] and a["probability"]<a["alert_threshold"] and staffed(a)),r)
    return {"available":True,"patient_id":r["patient_id"],"recording_id":r["recording_id"],"fold":r["fold"],
        "cursor":max(5,r["index"]-3),"warning_cursor":r["index"],"outcome_cursor":r["index"]+2,"stable_cursor":stable["index"],"gap_cursor":r["index"],
        "issued_at":r["timestamp"],"current_glucose_mg_dl":r["current"],"population_forecast_mg_dl":r["population"],"hybrid_forecast_mg_dl":r["hybrid"],
        "actual_at_30_minutes_mg_dl":r["actual"],"event_probability":r["probability"],"alert_threshold":r["alert_threshold"],
        "curation_note":"Retrospectively selected out-of-fold episode during the virtual weekday09-17 demonstration window, favoring a clear warning and close hybrid forecast. This selected case does not establish clinical effectiveness or actual historical staffing."}


def evaluate(iterations=80,bootstrap=1000):
    recordings,manifest,profiles=load_recordings();protocol=freeze_protocol(recordings,iterations,bootstrap)
    legacy=OUT/"legacy_benchmark.json"
    if not legacy.exists(): legacy.write_bytes((OUT/"benchmark.json").read_bytes())
    print("Protocol frozen. Building causal native examples",flush=True)
    by_record={r["recording_id"]:make_examples(r) for r in recordings}
    all_predictions={h:[] for h in HORIZONS};fold_reports=[];bundles={}
    models_list=["population","hybrid","population_no_context","persistence","linear_trend"]
    with threadpool_limits(limits=1):
        for partition in protocol["outer_folds"]:
            fold=partition["fold"];print(f"Outer fold {fold}/5: grouped inner selection",flush=True)
            subsets={name:[r for r in recordings if r["patient_id"] in partition[name]] for name in ["training","calibration","evaluation"]}
            training={h:[row for r in subsets["training"] for row in by_record[r["recording_id"]][h]] for h in HORIZONS}
            parameters,inner=inner_select(training[30],iterations)
            print(f"Fold {fold}: train models and dedicated excursion classifiers",flush=True)
            models,ablations,classifiers=train(training,parameters,iterations)
            calibration=predict(subsets["calibration"],by_record,models,ablations,classifiers,fold)
            intervals,calibrators,thresholds,audit=calibrate(calibration)
            testing=predict(subsets["evaluation"],by_record,models,ablations,classifiers,fold)
            apply_calibration(testing,intervals,calibrators,thresholds)
            for h,rows in testing.items(): all_predictions[h].extend(rows)
            fold_metrics=[metrics(testing[h],model,h,"all",bootstrap) for h in HORIZONS for model in models_list]
            fold_report={"fold":fold,"patient_ids":partition,"selected_parameters":parameters,"inner_selection":inner,"metrics":fold_metrics,
                "events":{str(h):episode_metrics(testing[h],thresholds[h]) for h in HORIZONS},"calibration":audit}
            fold_reports.append(fold_report)
            bundles[fold]={"models":models,"classifiers":classifiers,"probability_calibrators":calibrators,"intervals":intervals,"alert_thresholds":thresholds,
                "adaptation":ADAPTATION,"feature_names":FEATURE_NAMES,"training_patient_ids":partition["training"],"calibration_patient_ids":partition["calibration"],
                "evaluation_patient_ids":partition["evaluation"],"metadata":{"version":f"clinic-v1-fold-{fold}","fold":fold,"source":"ShanghaiT2DM","native_cadence_minutes":15}}
            print(f"Fold {fold} done.30m population={next(m['mae'] for m in fold_metrics if m['model']=='population' and m['horizon_minutes']==30):.3f}",flush=True)
    metric_rows=[metrics(all_predictions[h],model,h,phase,bootstrap) for h in HORIZONS for model in models_list for phase in ["all","cold_start","adapted"]]
    comparisons=[paired(all_predictions[h],left,right,bootstrap) for h in HORIZONS for left,right in [("hybrid","population"),("population","population_no_context"),("population","persistence")]]
    gate=next(c for c in comparisons if c["model"]=="hybrid" and c["horizon_minutes"]==30)
    primary="hybrid" if gate["supported_improvement"] else "population"
    demo=select_demo(all_predictions[30]);demo_fold=demo.get("fold",1)
    bundle=bundles[demo_fold]
    bundle["metadata"].update({"primary":primary,"personalization_status":"supported_internal_retrospective" if primary=="hybrid" else "experimental",
        "primary_gate":gate,"runtime_note":"The demonstration serves one outer-fold model; OOF benchmark metrics combine all five independently fitted outer models."})
    # Retain other folds to support honest per-patient OOF routing in replay.
    bundle["fold_bundles"]={fold:b for fold,b in bundles.items() if fold!=demo_fold}
    bundle["patient_folds"]={pid:part["fold"] for part in protocol["outer_folds"] for pid in part["evaluation"]}
    for b in bundle["fold_bundles"].values(): b["metadata"].update({"primary":primary,"personalization_status":bundle["metadata"]["personalization_status"]})
    worst=sorted(all_predictions[30],key=lambda r:abs(r[primary]-r["actual"]),reverse=True)[:5]
    failures=[{k:r[k] for k in ["patient_id","recording_id","timestamp","index","current","actual","population","hybrid","probability","alert_threshold","fold"]} for r in worst]
    reliability={}
    for h,rows in all_predictions.items():
        eligible=[r for r in rows if r["event_eligible"]];bins=[]
        for lo in np.arange(0,1,.1):
            group=[r for r in eligible if lo<=r["probability"]<(lo+.1 if lo<.9 else 1.00001)]
            if group: bins.append({"lower":float(lo),"upper":float(lo+.1),"n":len(group),"mean_probability":float(np.mean([r["probability"] for r in group])),"observed_frequency":float(np.mean([r["event"] for r in group]))})
        reliability[str(h)]=bins
    candidate_origins=sum(max(0,len(r["observations"])-4) for r in recordings)
    native_valid_origins=sum(len(past_valid_origins(recording)) for recording in recordings)
    data_checks={"eligible_forecast_origins_30":len(all_predictions[30]),"candidate_origins_after_history":candidate_origins,
        "abstention_or_unscorable_fraction":float(1-len(all_predictions[30])/candidate_origins),
        "past_valid_forecast_origins":native_valid_origins,
        "real_time_abstention_fraction_including_initial_warmup":float(1-native_valid_origins/manifest["observations"]),
        "note":"Includes native-gap abstention and end-of-recording origins with unavailable future labels; not pure real-time abstention."}
    benchmark={"generated_at":datetime.now(timezone.utc).isoformat(),"status":"measured","protocol":protocol,"cohort":{"patients":manifest["patients"],"recordings":manifest["recordings"],"observations":manifest["observations"]},
        "model_labels":{"population":"Boosted population + baseline context","hybrid":"Population + matured patient residual correction","population_no_context":"Boosting without baseline context","persistence":"Last observed glucose","linear_trend":"OLS trend on last five readings"},
        "metrics":metric_rows,"folds":fold_reports,"comparisons":comparisons,"event_metrics":{str(h):event_fold_metrics(rows, recordings) for h,rows in all_predictions.items()},
        "probability_reliability":reliability,"primary_model":primary,"personalization_status":bundle["metadata"]["personalization_status"],"primary_gate":gate,
        "failure_cases":failures,"demo":demo,"data_quality":data_checks,
        "limitations":["Internal retrospective validation; this entire public cohort and legacy split were inspected before this experiment.",
            "No independent external, prospective, clinical, or Indian population validation.","Historical age/sex/BMI/duration are assumed available at baseline; untimed labs, medications, and outcomes excluded.",
            "Empirical fixed intervals and calibrated probabilities need prospective reliability assessment; no unconditional coverage guarantee.",
            "Alert thresholds were selected on calibration patients; test alert burden may exceed the calibration budget.",
            "24 eligible hours means below/equal180 valid native forecast time, not all calendar time or a verified staffed clinic schedule.",
            "Cold start is online adaptation during first24h, not zero-shot; state resets for every recording.",
            "Twin is an engineering forecast model, not physiological metabolism, medication advice, or treatment simulation.",
            "Fold-wise median warning lead times are aggregated as a median of fold medians; event confidence intervals remain future work.",
            "Doctor operating-point and workflow review remains pending; frozen protocol is an engineering experiment, not clinical acceptance.",
            "Demo staffing uses a labeled historical virtual local clock; source timezone and actual historical staffing are unverified."],
        "runtime":{"demo_fold":demo_fold,"patient_fold_routing":True,"note":"Use a patient's outer evaluation fold at runtime; unseen imported patients use the demo-fold model and are out of distribution."},
        "versions":{"python":sys.version.split()[0],"numpy":np.__version__,"scikit_learn":sklearn.__version__}}
    joblib.dump(bundle,OUT/"clinic_model.joblib",compress=3)
    (OUT/"clinic_benchmark.json").write_text(json.dumps(benchmark,indent=2,allow_nan=False))
    for h,rows in all_predictions.items():
        slim=[{k:v for k,v in r.items() if k not in ["widths"]} for r in rows]
        # Compressed ledger enables independent metric verification without model retraining.
        joblib.dump(slim,OUT/f"clinic_oof_{h}.joblib",compress=3)
    print("Primary:",primary,"Gate:",gate,flush=True)
    for m in metric_rows:
        if m["phase"]=="all": print(f"{m['horizon_minutes']}m {m['model']} MAE={m['mae']:.3f} coverage={m['interval_coverage']:.3f}",flush=True)
    print("Events:",benchmark["event_metrics"],"Demo:",demo,flush=True)
    return benchmark


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--iterations",type=int,default=80);parser.add_argument("--bootstrap",type=int,default=1000)
    arguments=parser.parse_args();evaluate(arguments.iterations,arguments.bootstrap)
