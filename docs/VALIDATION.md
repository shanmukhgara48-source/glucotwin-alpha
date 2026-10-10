# Local validation - 10 October 2026

## Implemented and checked

- Real ShanghaiT2DM: 100 base patients, 109 recordings, 112,462 measured observations; 13 missing rows excluded and 11 native gaps retained.
- Patient-separated population training, separate interval calibration and held-out evaluation. Two independent training runs reproduced the same reported scores.
- Pure prefix-only forecasts; changing future observations did not alter an earlier snapshot.
- Independent patient replay; changing patients and returning reproduced the original state.
- Intentionally withholding three recent readings produced a 45-minute freshness gap and suppressed both forecast arrays and warnings.
- Future target actuals stayed hidden until their timestamps were reached.
- Patient parameter adaptation was visible alongside the training prior. Alert acknowledgement remained display-only.
- `python -m pytest backend/tests tests -q`: **16 passed**.
- `npm --prefix frontend run build`: production build passed.
- Final browser demo path: **three consecutive fresh-page runs passed**, without browser console errors. Each run exercised warning, acknowledgement, observed outcome, stable/gap episodes, patient switch, reset, step, play/pause, benchmark and provenance.
- Presentation layout inspected at 1440px; mobile layout checked at 390px with document width equal to viewport width.
- Launcher tested on alternate local ports, including frontend-to-API proxy and real-model replay. Ctrl+C removed both owned listening services; unrelated services were preserved.

## Measured limitations

At 30 minutes, population MAE is 10.53 mg/dL, persistence 12.76, personalized filter 14.48 and pooled filter 14.81. The personalized model is not the strongest forecaster. Removing baseline context improves the population result in this split. The 60-minute same-filter improvement is inconclusive under the paired patient bootstrap.

Precision/recall are overlapping forecast-window metrics; false-alert episodes use a 30-minute cooldown and eligible below-threshold forecast time as their patient-day denominator. The native sampling resolution is 15 minutes. These results do not establish prospective clinical performance.

The build has a non-blocking Vite bundle-size warning (the chart/UI bundle is about 201 KB compressed) and a Starlette test-client deprecation warning. Neither caused a build, runtime or test failure.

## Not established

No hosted release, live sensor integration, prospective clinical validation, validated physiological simulation, medication advice, causal treatment effect or Indian clinical generalization. Repeated patient splits, improved adaptation, a separate cohort, final presentation/video and platform submission remain later milestones.
