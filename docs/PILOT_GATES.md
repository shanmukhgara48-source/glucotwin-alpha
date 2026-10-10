# Gates before clinical use

## v0.3 release boundary

Only `GLUCOTWIN_ENV=research` is enabled. No genuine device source or clinic authorization has been supplied; `clinic_pending` connections cannot ingest readings. Patient forecast alerts stay disabled. Enrollment and server generators create separate synthetic identities. The clinical-source packet is prepared for participant-owned outreach; no outreach has been sent.

Local cookie/CSRF sessions, role isolation, optional encrypted TOTP, invitation/deactivation, durable ingestion, revision conflicts, encrypted SQLite recovery and model rollback are implemented. PostgreSQL migrations and a scoped intake/worker integration were tested against an isolated local database. These checks do not establish an operational clinical deployment.

The source SQLite database is plaintext. Off-host recovery, verified TLS/encrypted deployment, mandatory operational-staff MFA/access review, applicable approvals and prospective clinical thresholds remain pending.

The current software is a research clinic-workflow prototype. The gate status below starts as pending; engineering checks are documented separately in VALIDATION.md.

| Gate | Evidence to collect | Status |
|---|---|---|
| Intended use and workflow | Adult T2D population, staffing, responsibilities, response/escalation rules, contraindications and acceptable alert burden reviewed by clinical partner | Pending |
| Retrospective prediction evidence | Frozen protocol, grouped patient evaluation, calibrated probabilities/intervals, missed events, alert burden, subgroups and failure cases | Internal evaluation only |
| Indian applicability | Independent cohort or prospective protocol representative of intended clinic and device use | Pending |
| Device integration | Authorized access, exact identity/units, observation and arrival times, measured latency, outage/reconnection handling | Simulated/CSV only |
| Privacy and operations | Applicable obligations, consent, retention/export/deletion, encrypted storage/transport, protected backups, monitoring and incident response | Pending full pilot review |
| Regulatory/ethics assessment | Intended-use/classification assessment and applicable approval for clinical investigation or clinical deployment | Pending |
| Prospective shadow evaluation | Frozen model forecasts recorded without influencing care under approved protocol | Pending |
| Supervised clinical release | Agreed evidence requirements passed; trained staffing and rollback/stop procedure in place | Pending |

Do not infer compliance or clinical readiness from research labels, an authenticated UI, or successful local tests.

## Change and stop rules

Version every model and preserve its evaluation report and checksum. Deploy only a reviewed version. A new model or operating threshold requires repeat evaluation. Stop active warnings if source latency, patient identity, unit handling, data completeness, staffing or model availability is unsupported. Retain records for audit and investigate before resuming.

## Primary references

- [CDSCO Medical Device Software guidance](https://www.cdsco.gov.in/opencms/export/sites/CDSCO_WEB/Pdf-documents/Guidance-document-on-Medical-Device-Software-under-MDR-2017.pdf)
- [IMDRF clinical evaluation](https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation)
- [Published ABDM FHIR R4 guide](https://www.nrces.in/ndhm/fhir/r4/index.html)
- [Dexcom access process](https://developer.dexcom.com/docs/dexcom/scopes-access)
