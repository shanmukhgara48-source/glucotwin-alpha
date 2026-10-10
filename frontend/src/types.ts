export interface Patient {
  id: string;
  display_name: string;
  name?: string;
  source?: string;
  age: number | null;
  sex: string | null;
  bmi: number | null;
  diabetes_duration_years: number | null;
  recording_id: string;
  dataset: string;
  observation_count?: number;
  evaluation_partition?: string;
}
export interface Observation { timestamp: string; glucose_mg_dl: number }
export interface Forecast extends Observation { horizon_minutes: number; lower: number | null; upper: number | null; interval_method?: string; nominal_coverage?: number; event_probability?: number; probability?: number }
export interface Update { timestamp: string; observed: number; predicted_before_update: number; innovation: number; gain: number; level: number; trend: number }
export interface Snapshot {
  patient: Patient; cursor: number; total_observations: number; current_time: string;
  observations: Observation[];
  forecasts: { twin: Forecast[]; population: Forecast[]; [key: string]: unknown };
  quality: { status: string; message: string; last_reading_at: string; minutes_since_reading: number };
  state: { level: number; trend: number; innovation: number; updates: number; adaptation_samples: number; uncertainty: number; parameters: Record<string, number>; pooled_parameters?: Record<string, number> };
  update_history: Update[];
  alerts: { id: string; type: string; message: string; horizon_minutes: number; predicted_crossing_at: string; threshold: number }[];
  forecast_history: { issued_at: string; target_time: string; horizon_minutes: number; twin: number; population: number; actual: number | null }[];
  scenario: string;
  intervals?: { nominal_coverage: number; twin_calibrated: boolean; population_calibrated: boolean; message: string };
  primary_model?: string;
  hybrid?: Record<string, unknown>;
  event_probabilities?: Record<string, number>;
  adaptation?: Record<string, unknown>;
  event_risks?: { horizon_minutes: number; probability: number; threshold: number; exceeds_threshold: boolean; event_eligible: boolean; ongoing_high: boolean }[];
  model?: { version: string; primary: string; personalization_status: string; evidence?: unknown };
  monitoring?: Monitoring;
  clinic_model?: { forecasts: { population: Forecast[]; hybrid: Forecast[] }; model: NonNullable<Snapshot['model']>; event_risks: NonNullable<Snapshot['event_risks']>; adaptation: Record<string, unknown>; forecast_history: { issued_at: string; target_at: string; horizon_minutes: number; population_mg_dl: number; hybrid_mg_dl: number; actual_mg_dl: number | null }[] };
}
export interface Metric {
  model: string; horizon_minutes: number; phase: string; n_predictions: number; n_patients: number;
  mae: number | null; rmse: number | null; mae_ci?: [number, number] | null; precision: number | null; recall: number | null;
  false_alerts_per_patient_day: number | null; warning_lead_time_minutes: number | null; interval_coverage: number | null; mean_interval_width: number | null;
}
export interface Benchmark {
  generated_at: string; status: string; protocol: Record<string, unknown>; cohort: Record<string, number>;
  metrics: Metric[]; failures: string[]; limitations: string[];
  demo?: { patient_id: string; cursor: number; warning_cursor?: number; outcome_cursor?: number; stable_cursor: number; gap_cursor: number; curation_note?: string };
  failure_cases?: { patient_id: string; recording_id: string; timestamp: string; current: number; prediction: number; actual: number }[];
  model_labels?: Record<string, string>;
  [key: string]: unknown;
}
export type Provenance = Record<string, unknown>;
export interface User { id: string; username: string; name?: string; role: 'admin' | 'reviewer'; clinic_id: string }
export interface Monitoring { timezone: string; start_hour: number; end_hour: number; reviewer_id: string; days: number[]; active?: boolean; current_time?: string; clock_kind?: string }
export interface ReviewItem { id: string; patient_id: string; patient_name?: string; type: string; status: string; issued_at: string; reading_freshness?: number | string | { minutes_since_reading?: number; age_at_issue_minutes?: number; status?: string; clock_kind?: string }; assigned_reviewer?: string; last_review?: string | null; next_review_at?: string | null; overdue?: boolean; message?: string; probability?: number | null; forecast_id?: string; cursor?: number; scenario?: string; actions?: ReviewAction[] }
export interface ReviewAction { id?: string; status: string; reason: string; note: string; next_review_at?: string | null; reviewer?: string; reviewer_id?: string; actor_id?: string; recorded_at?: string; created_at?: string; timestamp?: string }
export interface QueueData { items: ReviewItem[]; monitoring: Monitoring; pending_count: number; overdue_count?: number }
export interface TimelineEvent { id?: string; type?: string; kind?: string; timestamp?: string; observed_at?: string; available_at?: string; provenance?: string; source?: string; value?: unknown; message?: string; note?: string; [key: string]: unknown }
