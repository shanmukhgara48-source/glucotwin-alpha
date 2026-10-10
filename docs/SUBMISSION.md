# Submission workstream

The application is the first working research prototype. The final hackathon package still needs the following completed artifacts and checks.

## Required package

- Team and college identity in the README and platform fields (supply real details; do not invent contributors).
- Public GitHub repository with working setup commands, code license and dataset attribution.
- Architecture and presentation exported to PDF/PPT.
- Accessible explanation/demo video with an exported duration of at least 20 minutes.
- Folder named `Team Name_College Name`, with links checked in a logged-out browser.

Official brief: https://unstop.com/hackathons/crp-digital-twin-challenge-2026-happiest-health-1757873/amp

Published deadlines checked during strategy research: registration 18 October 2026, 7 PM IST; prototype submission 20 October 2026, 7 PM IST. Recheck current platform details before relying on these dates. Keep the final two hours for submission checks.

## Three-minute core journey

| Time | Action | Evidence to point at |
|---|---|---|
| 0:00-0:20 | Open a patient | Anonymized source ID, baseline context, recorded-data label |
| 0:20-0:50 | Start/step playback | New readings, state updates and patient parameter changes |
| 0:50-1:30 | Inspect warning; reveal later outcome | Prediction issued before crossing, then actual measurement |
| 1:30-2:10 | Compare models | Same history, personalized/population predictions and intervals |
| 2:10-2:40 | Enable sensor-gap scenario | Missing observations, freshness, forecast suppression |
| 2:40-3:00 | Open benchmark/failure case | Actual held-out results, negative findings and limitations |

Curated examples are demonstration selections from measured results, not evidence of overall accuracy. Include a false warning or missed event. Never pick an outcome first and present it as an unselected prospective clinical trial.

## 22-minute recording outline

1. Problem and doctor workflow: 2 minutes.
2. Data provenance, cohort, timing and licenses: 3 minutes.
3. Architecture, filtering, personalization and causal replay: 4 minutes.
4. Core journey, stable example and failure/missing-data example: 5 minutes.
5. Evaluation splits, baselines, metrics and uncertainty: 4 minutes.
6. Related work, cohort limits and unsupported claims: 2 minutes.
7. Fresh setup and reproducibility: 2 minutes.

## Claim check before recording

- Call it an engineering state filter with patient parameter adaptation; do not claim a validated physiological simulator.
- Describe the measured result, including negative or inconclusive personalization findings.
- Keep cold-start, post-24-hour adaptation and nominal interval coverage distinct.
- State that baseline-context timing is an assumption where source timestamps are unavailable.
- Label recorded observations and intentionally withheld sensor-gap scenarios.
- No clinical validation, medication dosing, remission, live sensor integration or Indian generalization claim.
- No numeric risk probability unless independently calibrated; a point forecast crossing a threshold is a research warning.

## Pre-demo check

- Start fresh and run the exact path three times consecutively.
- Verify no browser console errors, visible data freshness and correct patient resets.
- Confirm every earlier prediction is invariant to future-record changes.
- Test on the presentation screen resolution.
- Keep a recording and screenshots as backup; preserve a known-working Git commit.
- Freeze optional features on 17 October and protect recording/packaging time.
