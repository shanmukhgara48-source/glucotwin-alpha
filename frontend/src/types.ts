export interface Patient {
  id: string;
  display_name: string;
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
export interface Forecast extends Observation { horizon_minutes: number; lower: number | null; upper: number | null; interval_method?: string; nominal_coverage?: number }
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
