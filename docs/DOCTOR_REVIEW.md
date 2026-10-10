# Doctor review packet

Status: **pending**. No doctor review or clinical effectiveness has been established by this build.

## Intended workflow

Adult Type 2 diabetes; clinic care team reviewing predicted high-glucose excursions during explicitly staffed windows. The research target is any measured glucose above 180 mg/dL within 30 minutes; 60 minutes is reported separately. No automated medication or treatment instructions.

Use only the bundled anonymized Shanghai records and clearly synthetic scenarios during review. Do not enter private patient details or identify participants.

## Review 1: workflow and operating point

Record reviewer name/role privately, date, reviewed software/model version, and any conflicts. Agree monitoring hours, assigned reviewer, expected review delay, escalation ownership, and when the system should abstain. The initial engineering budget is at most one false-alert episode per 24 eligible forecast hours; this is not a medical standard. Clinical acceptance criteria remain pending.

## Five cases

| Case | Task | Record |
|---|---|---|
| Advance warning | Locate evidence, probability, issue time, and eventual observed outcome | Was the meaning clear? Was the next step appropriate? |
| Stable patient | Establish what a low forecast probability does and does not mean | Was uncertainty understood? |
| Sensor gap | Identify the last reading and why forecasts paused | Was missing data confused with low risk? |
| Uncertain prediction | Inspect interval, maturity, and recent forecast errors | Did the display overstate confidence? |
| Misleading prediction | Review an actual false alert or missed episode from the benchmark | Could the doctor find the failure and its limitations? |

For each task record completion, time taken, misunderstandings, proposed changes, severity, and resolution. Do not record a task as passed unless it was actually performed.

## Review 2: revised prototype

Repeat failed tasks after revisions. Review examples of false alarms, missed episodes, short/fragmented recordings, outside-hours operation, duplicate readings, and patient identity mismatches. Verify that acknowledgement affects workflow only, not prediction accuracy.

## Release evidence

- Workflow/usable display: pending doctor feedback.
- Predictive accuracy: retrospective patient-separated evaluation only.
- Live-device timing and prospective Indian performance: not established.
- Clinical-use approval: pending applicable assessment and approvals.

Store a dated feedback record with the reviewed commit/model version. Summaries in the presentation must distinguish requested review, completed feedback, and clinical validation.
