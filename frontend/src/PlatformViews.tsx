import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Check,
  ClipboardCheck,
  Download,
  FileCheck2,
  HeartHandshake,
  Link2,
  LockKeyhole,
  Plus,
  RefreshCw,
  ShieldCheck,
  UserRoundPlus,
} from "lucide-react";
import { api, download, post } from "./api";
import type { User } from "./types";
import {
  Chip,
  Empty,
  ErrorBox,
  Field,
  Heading,
  human,
  input,
  Loading,
  Metric,
  Modal,
  number,
  outline,
  Section,
  solid,
  timestamp,
} from "./Design";
import { IntakeView, MonitoringView } from "./ClinicViews";

type Row = Record<string, unknown>;
function SourceSetup({ refresh }: { refresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("Synthetic research sensor");
  const [patient, setPatient] = useState("SIM-COMPANION");
  const [kind, setKind] = useState("synthetic");
  const [code, setCode] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [cadence, setCadence] = useState(15);
  const [seeded, setSeeded] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      post<Row>("/v2/connections", {
        name,
        source_type: kind,
        ...(kind === "synthetic" ? { patient_id: patient } : {}),
        cadence_minutes: cadence,
        source_timezone: "Asia/Kolkata",
      }),
    onSuccess: (r) => {
      setCode(String(r.connection_key || ""));
      setSourceId(String(r.id || (r.connection as Row | undefined)?.id || ""));
      refresh();
    },
  });
  const generator = useMutation({
    mutationFn: () =>
      post("/v2/connections/" + sourceId + "/generator", {
        enabled: true,
        seed: true,
      }),
    onSuccess: () => {
      setSeeded(true);
      refresh();
    },
  });
  return (
    <>
      <button
        className={solid}
        onClick={() => {
          setOpen(true);
          setCode("");
          setSourceId("");
          setSeeded(false);
        }}
      >
        <Plus size={16} />
        Configure research source
      </button>
      <Modal
        open={open}
        setOpen={setOpen}
        title="Configure a source connection"
        description="Synthetic connections use a real ingestion worker with generated data. Clinical connections remain pending until their external gates pass."
      >
        {sourceId ? (
          <div className="space-y-4">
            <Chip tone="teal">Source created</Chip>
            {code && (
              <Field
                label="Private connection key"
                hint="Shown once. Keep this credential out of recordings and public files."
              >
                <input className={input + " font-mono"} value={code} readOnly />
              </Field>
            )}
            {kind === "synthetic" && !seeded && (
              <>
                <p className="text-sm leading-relaxed text-slate-500">
                  Start continuous generated collection. Eight past synthetic
                  readings are explicitly seeded; future readings arrive on the
                  source cadence, independently of the browser. These readings
                  are excluded from measured benchmarks.
                </p>
                <button
                  className={solid + " w-full"}
                  disabled={generator.isPending}
                  onClick={() => generator.mutate()}
                >
                  Start synthetic generator
                </button>
              </>
            )}
            {seeded && (
              <p
                role="status"
                className="text-sm leading-relaxed text-teal-800"
              >
                Synthetic generator started. The worker will ingest the seeded
                observations and issue supported forecasts. Native 15-minute
                future readings continue while the source is enabled.
              </p>
            )}
            <ErrorBox error={generator.error} />
            <button
              className={outline + " w-full"}
              onClick={() => {
                setCode("");
                setOpen(false);
              }}
            >
              Done
            </button>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Source name">
              <input
                className={input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </Field>
            <Field label="Source type">
              <select
                className={input}
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="synthetic">
                  Generated synthetic research source
                </option>
                <option value="clinic_pending">
                  Clinical integration — pending
                </option>
              </select>
            </Field>
            {kind === "synthetic" && (
              <Field label="Synthetic patient ID">
                <input
                  className={input}
                  value={patient}
                  onChange={(e) => setPatient(e.target.value)}
                  required
                  pattern="SIM-.+"
                />
              </Field>
            )}
            <Field
              label="Observation cadence"
              hint="The current model is evaluated at 15-minute cadence. A faster generated feed demonstrates intake but cannot claim compatible forecasting."
            >
              <select
                className={input}
                value={cadence}
                onChange={(e) => setCadence(Number(e.target.value))}
              >
                <option value={15}>15 minutes · current model cadence</option>
                <option value={1}>1 minute · intake only</option>
              </select>
            </Field>
            <ErrorBox error={create.error} />
            <button className={solid + " w-full"} disabled={create.isPending}>
              Create source connection
            </button>
          </form>
        )}
      </Modal>
    </>
  );
}
function SourceActions({
  connection,
  refresh,
}: {
  connection: Row;
  refresh: () => void;
}) {
  const [key, setKey] = useState("");
  const [open, setOpen] = useState(false);
  const mutation = useMutation({
    mutationFn: ({ route, body }: { route: string; body: object }) =>
      post<Row>("/v2/connections/" + connection.id + route, body),
    onSuccess: (r) => {
      if (r.connection_key) {
        setKey(String(r.connection_key));
        setOpen(true);
      }
      refresh();
    },
  });
  return (
    <>
      <div className="mt-3 flex flex-wrap gap-2">
        {connection.source_type !== "clinic_pending" && (
          <button
            className={outline}
            disabled={mutation.isPending || connection.status === "revoked"}
            onClick={() =>
              mutation.mutate({
                route: "/generator",
                body: { enabled: true, seed: false },
              })
            }
          >
            Continue synthetic generator
          </button>
        )}
        <button
          className={outline}
          disabled={mutation.isPending || connection.status === "revoked"}
          onClick={() => mutation.mutate({ route: "/rotate-key", body: {} })}
        >
          Rotate connection key
        </button>
      </div>
      <ErrorBox error={mutation.error} />
      <Modal
        open={open}
        setOpen={(v) => {
          setOpen(v);
          if (!v) setKey("");
        }}
        title="Connection key rotated"
        description="The old key has been revoked. Copy the new key privately; it is displayed once."
      >
        <Field label="New private key">
          <input className={input + " font-mono"} value={key} readOnly />
        </Field>
      </Modal>
    </>
  );
}
export interface Operations {
  server_time: string;
  counts: {
    pending_jobs: number;
    failed_jobs: number;
    quarantined_events: number;
    open_reviews: number;
    overdue_reviews: number;
    issued_forecasts: number;
  };
  connections: Row[];
  worker: { last_heartbeat_at?: string; status: string };
  clinical_connection: string;
  mode: string;
}
export function OperationsView({ user }: { user: User }) {
  const query = useQuery({
    queryKey: ["operations"],
    queryFn: () => api<Operations>("/v2/operations"),
    refetchInterval: 10000,
  });
  const gates = useQuery({
    queryKey: ["gates"],
    queryFn: () => api<Row>("/v2/platform/gates"),
  });
  const [notice, setNotice] = useState("");
  const mutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      post("/v2/connections/" + id, { status: action }, "PATCH"),
    onSuccess: () => {
      setNotice("Source state updated.");
      void query.refetch();
    },
  });
  const data = query.data;
  return (
    <div className="space-y-6">
      <Heading
        overline="Operations and source health"
        title="Know when the system needs attention."
        actions={
          <>
            {user.role === "admin" && (
              <SourceSetup refresh={() => void query.refetch()} />
            )}
            <button className={outline} onClick={() => void query.refetch()}>
              <RefreshCw size={16} />
              Refresh status
            </button>
          </>
        }
      >
        Connection health, forecast eligibility, and staffed care are separate
        responsibilities.
      </Heading>
      <ErrorBox error={query.error || mutation.error} />
      {notice && (
        <p
          role="status"
          className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800"
        >
          {notice}
        </p>
      )}
      {query.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Issued forecasts"
              value={data?.counts.issued_forecasts ?? "—"}
              note="Persisted, immutable receipts"
            />
            <Metric
              label="Pending ingestion jobs"
              value={data?.counts.pending_jobs ?? "—"}
              note="Awaiting worker processing"
            />
            <Metric
              label="Failed jobs"
              value={data?.counts.failed_jobs ?? "—"}
              tone={(data?.counts.failed_jobs || 0) > 0 ? "amber" : "neutral"}
              note="Requires operator investigation"
            />
            <Metric
              label="Quarantined events"
              value={data?.counts.quarantined_events ?? "—"}
              note="Excluded from forecasting"
            />
          </div>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Section
              title="Source connections"
              kicker="Research collection only"
            >
              {data?.connections?.length ? (
                <div className="space-y-4">
                  {data.connections.map((c, i) => (
                    <div
                      key={String(c.id || i)}
                      className="rounded-xl border border-slate-200 p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                            <Link2 size={16} />
                            {String(
                              c.name || c.label || c.id || "Source connection",
                            )}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            {human(c.kind || c.source_type || c.type)} ·{" "}
                            {String(c.patient_id || "Clinic source")}
                          </p>
                        </div>
                        <Chip
                          tone={
                            ["active", "enabled"].includes(String(c.status))
                              ? "violet"
                              : "neutral"
                          }
                        >
                          {human(c.status)}
                        </Chip>
                      </div>
                      <p className="mt-3 text-sm leading-relaxed text-slate-500">
                        {String(
                          c.disclosure ||
                            c.description ||
                            "Generated synthetic readings demonstrate an actual ingestion and forecast pipeline. This source is not a clinical wearable connection.",
                        )}
                      </p>
                      <p className="mt-3 text-xs text-slate-500">
                        Last received:{" "}
                        {timestamp(
                          typeof c.last_received_at === "string"
                            ? c.last_received_at
                            : undefined,
                        )}
                      </p>
                      {user.role === "admin" && (
                        <div className="mt-4 flex flex-wrap gap-2">
                          <button
                            className={outline}
                            disabled={mutation.isPending}
                            onClick={() =>
                              mutation.mutate({
                                id: String(c.id),
                                action:
                                  String(c.status) === "enabled"
                                    ? "paused"
                                    : "enabled",
                              })
                            }
                          >
                            {String(c.status) === "enabled"
                              ? "Pause source"
                              : "Resume source"}
                          </button>
                          <button
                            className={outline}
                            disabled={
                              mutation.isPending ||
                              String(c.status) === "revoked"
                            }
                            onClick={() =>
                              mutation.mutate({
                                id: String(c.id),
                                action: "revoked",
                              })
                            }
                          >
                            Revoke research source
                          </button>
                        </div>
                      )}
                      {user.role === "admin" && (
                        <SourceActions
                          connection={c}
                          refresh={() => void query.refetch()}
                        />
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No source connection configured">
                  An administrator can start the synthetic demonstration source.
                  Clinical device access remains pending.
                </Empty>
              )}
            </Section>
            <div className="space-y-5">
              <Section title="Monitoring worker">
                <Chip
                  tone={
                    data?.worker.status === "running" ||
                    data?.worker.status === "healthy"
                      ? "teal"
                      : "amber"
                  }
                >
                  <Activity size={12} />
                  {human(data?.worker.status)}
                </Chip>
                <p className="mt-3 text-sm text-slate-500">
                  Heartbeat {timestamp(data?.worker.last_heartbeat_at)}
                </p>
                <p className="mt-3 text-xs leading-relaxed text-slate-500">
                  A worker heartbeat confirms engineering activity. It does not
                  confirm clinical monitoring or patient safety.
                </p>
              </Section>
              <Section
                title="Clinical deployment gate"
                kicker="External evidence pending"
              >
                <Chip tone="amber">
                  <LockKeyhole size={12} />
                  {human(data?.clinical_connection || "pending")}
                </Chip>
                <p className="mt-3 text-sm leading-relaxed text-slate-500">
                  Doctor workflow review, authorized CGM integration, approvals,
                  and prospective validation must be completed before supervised
                  clinical release.
                </p>
                <details className="mt-4">
                  <summary className="min-h-11 cursor-pointer text-sm font-medium text-teal-800">
                    Inspect release gates
                  </summary>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
                    {JSON.stringify(
                      gates.data || { status: "pending" },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </Section>
            </div>
          </div>
          <p className="text-xs text-slate-500">
            Server status as of {timestamp(data?.server_time)} ·{" "}
            {human(data?.mode)} environment
          </p>
        </>
      )}
    </div>
  );
}

export function IntakeDesk({ user }: { user: User }) {
  const [csv, setCsv] = useState("");
  const [preview, setPreview] = useState<Row | null>(null);
  const [message, setMessage] = useState("");
  const check = useMutation({
    mutationFn: () => post<Row>("/v2/platform/intake/preview", { csv }),
    onSuccess: setPreview,
  });
  const patients = useQuery({
    queryKey: ["patients"],
    queryFn: () => api<Row[]>("/patients"),
  });
  const client = useQueryClient();
  return (
    <div className="space-y-6">
      <Heading
        overline="Data intake"
        title="Validate before records enter the twin."
      >
        Identity, units, observation time, and arrival time remain part of the
        evidence.
      </Heading>
      <Section title="CSV preflight preview" kicker="Read-only validation">
        <p className="text-sm leading-relaxed text-slate-500">
          Paste an anonymized synthetic CSV to inspect errors before importing.
          The preview itself creates no records.
        </p>
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            check.mutate();
          }}
        >
          <Field label="CSV for preview">
            <textarea
              aria-label="CSV preview input"
              className={input + " min-h-32 font-mono text-sm"}
              value={csv}
              onChange={(e) => {
                setCsv(e.target.value);
                setPreview(null);
              }}
              required
              placeholder="patient_id,timestamp,glucose_mg_dl,available_at,source"
            />
          </Field>
          <button
            className={outline}
            disabled={check.isPending || user.role !== "admin"}
          >
            <FileCheck2 size={16} />
            {check.isPending ? "Checking rows…" : "Preview validation"}
          </button>
        </form>
        <ErrorBox error={check.error} />
        {preview && (
          <div
            role="status"
            className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4"
          >
            <p className="text-sm font-semibold text-slate-800">
              Validation result
            </p>
            <pre className="mt-3 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-600">
              {JSON.stringify(preview, null, 2)}
            </pre>
          </div>
        )}
      </Section>
      <div className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm leading-relaxed text-teal-900">
        The following adapter supports synthetic data and allowlisted anonymized
        public data. Identifiable clinical records remain outside this release.
      </div>
      <IntakeView
        user={user}
        patient={
          patients.data?.find((p) => String(p.id).startsWith("SIM-")) as never
        }
        imported={() => {
          void client.invalidateQueries({ queryKey: ["patients"] });
          void client.invalidateQueries({ queryKey: ["queue"] });
          setMessage(
            "Import completed. Inspect the patient timeline to review the available data.",
          );
        }}
      />
      {message && (
        <p
          role="status"
          className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800"
        >
          {message}
        </p>
      )}
    </div>
  );
}

export function AdminView({ user }: { user: User }) {
  const client = useQueryClient();
  const staff = useQuery({
    queryKey: ["staff"],
    queryFn: () => api<{ items: User[] }>("/v2/platform/staff"),
  });
  const patients = useQuery({
    queryKey: ["platform-patients"],
    queryFn: () => api<{ items: Row[] }>("/v2/platform/patients"),
  });
  const audit = useQuery({
    queryKey: ["platform-audit"],
    queryFn: () => api<{ items: Row[] }>("/v2/platform/audit"),
  });
  const monitoring = useQuery({
    queryKey: ["monitoring"],
    queryFn: () => api<import("./types").Monitoring>("/clinic/monitoring"),
  });
  const [invite, setInvite] = useState(false);
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("clinician");
  const [patientId, setPatientId] = useState("");
  const [code, setCode] = useState("");
  const [enroll, setEnroll] = useState(false);
  const [enrollId, setEnrollId] = useState("SIM-");
  const [patientLabel, setPatientLabel] = useState("");
  const create = useMutation({
    mutationFn: () =>
      post<{ user: User; invitation_code: string }>("/v2/platform/staff", {
        username,
        name,
        role,
        ...(role === "patient" ? { patient_id: patientId } : {}),
      }),
    onSuccess: (r) => {
      setCode(r.invitation_code);
      void client.invalidateQueries({ queryKey: ["staff"] });
    },
  });
  const deactivate = useMutation({
    mutationFn: (id: string) =>
      post("/v2/platform/staff/" + id + "/deactivate", {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["staff"] }),
  });
  const enrollment = useMutation({
    mutationFn: () =>
      post("/v2/platform/enroll", {
        patient_id: enrollId,
        label: patientLabel,
        timezone: "Asia/Kolkata",
      }),
    onSuccess: () => {
      setEnroll(false);
      void client.invalidateQueries({ queryKey: ["platform-patients"] });
      void client.invalidateQueries({ queryKey: ["patients"] });
    },
  });
  return (
    <div className="space-y-6">
      <Heading
        overline="Clinic administration"
        title="People, permissions, and responsibility."
        actions={
          <>
            <button className={outline} onClick={() => setEnroll(true)}>
              <Plus size={16} />
              Enroll synthetic patient
            </button>
            <button
              className={solid}
              onClick={() => {
                setInvite(true);
                setCode("");
              }}
            >
              <UserRoundPlus size={16} />
              Invite a team member
            </button>
          </>
        }
      >
        Accounts remain clinic scoped. Patient access is linked to one record.
      </Heading>
      <ErrorBox error={staff.error || deactivate.error} />
      <Section
        title="Workspace accounts"
        kicker="Clinician, coordinator, and patient"
      >
        {staff.isPending ? (
          <Loading />
        ) : (
          <div className="space-y-3">
            {staff.data?.items.map((u) => (
              <div
                key={u.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"
              >
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    {u.name || u.username}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {u.username} · {human(u.role)}
                    {u.patient_id ? " · " + u.patient_id : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Chip>
                    {human(
                      (u as User & { active?: boolean }).active === false
                        ? "deactivated"
                        : u.role,
                    )}
                  </Chip>
                  {u.id !== user.id && (
                    <button
                      className={outline}
                      disabled={deactivate.isPending}
                      onClick={() => deactivate.mutate(u.id)}
                    >
                      Deactivate
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
      <MonitoringView
        initial={monitoring.data || null}
        user={user}
        saved={() => {
          void monitoring.refetch();
          void client.invalidateQueries({ queryKey: ["queue"] });
        }}
      />
      <Section
        title="Security and clinical gates"
        kicker="Evidence, before deployment"
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            ["Session", "HttpOnly cookie session; CSRF-protected changes."],
            [
              "Patient access",
              "One linked patient record and approved companion content.",
            ],
            [
              "Clinical use",
              "Prospective validation and authorized device access remain pending.",
            ],
          ].map(([k, v]) => (
            <div key={k} className="rounded-xl bg-slate-50 p-4">
              <ShieldCheck size={20} className="text-teal-700" />
              <h3 className="mt-3 text-sm font-semibold text-slate-800">{k}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{v}</p>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Recent audit events" kicker="Append-only activity">
        {audit.isPending ? (
          <Loading />
        ) : audit.data?.items.length ? (
          <div className="space-y-3">
            {audit.data.items.slice(0, 12).map((a, i) => (
              <div
                key={String(a.id || i)}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 last:border-0"
              >
                <div>
                  <p className="text-sm font-medium text-slate-700">
                    {human(a.action || a.type || a.event)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Actor{" "}
                    {String(a.actor_id || a.user_id || a.actor || "Recorded")}
                  </p>
                </div>
                <p className="text-xs text-slate-500">
                  {timestamp(
                    String(a.created_at || a.timestamp || a.recorded_at || ""),
                  )}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <Empty title="No audit events yet" />
        )}
      </Section>
      <Modal
        open={invite}
        setOpen={setInvite}
        title="Invite to this clinic"
        description="An invitation code is shown once. Share it privately with the intended person."
      >
        {code ? (
          <div className="space-y-4">
            <Chip tone="teal">Invitation created</Chip>
            <Field label="Private activation code">
              <input
                className={input + " font-mono"}
                value={code}
                readOnly
                aria-label="Private activation code"
              />
            </Field>
            <p className="text-sm text-slate-500">
              Open the sign-in page and choose Activate invitation. Keep this
              code out of recordings and public files.
            </p>
            <button
              className={solid + " w-full"}
              onClick={() => {
                setCode("");
                setInvite(false);
              }}
            >
              Done
            </button>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Name">
              <input
                className={input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </Field>
            <Field label="Username">
              <input
                className={input}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                pattern="[A-Za-z0-9_.-]+"
              />
            </Field>
            <Field label="Role">
              <select
                className={input}
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {["clinician", "coordinator", "patient"].map((r) => (
                  <option key={r} value={r}>
                    {human(r)}
                  </option>
                ))}
              </select>
            </Field>
            {role === "patient" && (
              <Field label="Linked patient">
                <select
                  className={input}
                  value={patientId}
                  onChange={(e) => setPatientId(e.target.value)}
                  required
                >
                  <option value="">Select patient</option>
                  {patients.data?.items.map((p) => (
                    <option key={String(p.id)} value={String(p.id)}>
                      {String(p.display_name || p.label || p.id)}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <ErrorBox error={create.error} />
            <button className={solid + " w-full"} disabled={create.isPending}>
              Create private invitation
            </button>
          </form>
        )}
      </Modal>
      <Modal
        open={enroll}
        setOpen={setEnroll}
        title="Enroll a research patient"
        description="This release accepts synthetic demonstration profiles. Clinical enrollment remains gated."
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            enrollment.mutate();
          }}
        >
          <Field label="Synthetic patient ID">
            <input
              className={input}
              value={enrollId}
              onChange={(e) => setEnrollId(e.target.value)}
              required
              pattern="SIM-.+"
            />
          </Field>
          <Field label="Display label">
            <input
              className={input}
              value={patientLabel}
              onChange={(e) => setPatientLabel(e.target.value)}
              required
            />
          </Field>
          <ErrorBox error={enrollment.error} />
          <button className={solid + " w-full"} disabled={enrollment.isPending}>
            Enroll patient
          </button>
        </form>
      </Modal>
    </div>
  );
}

interface Companion {
  patient: Row;
  observations: Row[];
  contexts: Row[];
  tasks: Row[];
  consents: Row[];
  connections: Row[];
  monitoring: Row;
  source_status: unknown;
  clinical_gate: unknown;
}
export function PatientCompanion() {
  const query = useQuery({
    queryKey: ["companion"],
    queryFn: () => api<Companion>("/v2/patient/me"),
    refetchInterval: 30000,
  });
  const [kind, setKind] = useState("meal");
  const [value, setValue] = useState("");
  const [at, setAt] = useState(
    new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16),
  );
  const [notice, setNotice] = useState("");
  const [withdraw, setWithdraw] = useState(false);
  const context = useMutation({
    mutationFn: () =>
      post("/v2/patient/context", {
        kind,
        value,
        observed_at: new Date(at).toISOString(),
      }),
    onSuccess: () => {
      setValue("");
      setNotice("Your context was saved and labeled self-reported.");
      void query.refetch();
    },
  });
  const consent = useMutation({
    mutationFn: (action: string) =>
      post("/v2/patient/consents", { action, purpose: "research_collection" }),
    onSuccess: () => {
      setWithdraw(false);
      setNotice("Your research collection preference was recorded.");
      void query.refetch();
    },
  });
  const complete = useMutation({
    mutationFn: (id: string) =>
      post("/v2/patient/tasks/" + id + "/complete", {}),
    onSuccess: () => void query.refetch(),
  });
  const d = query.data;
  const last = d?.observations.at(-1);
  const granted = d?.consents
    .slice(0, 1)
    .some(
      (c) =>
        c.action === "grant" && (c.active === true || c.withdrawn_at == null),
    );
  return (
    <div className="space-y-6">
      <Heading
        overline="Your care companion"
        title="Your record. Your next step."
        actions={
          <button
            className={outline}
            onClick={() =>
              void download(
                "/v2/patient/report",
                "GlucoTwin_My_Approved_Summary.pdf",
              ).catch((e) => setNotice(e.message))
            }
          >
            <Download size={16} />
            Approved summary
          </button>
        }
      >
        Share context with your care team and keep track of tasks they have
        published for you.
      </Heading>
      <ErrorBox
        error={query.error || context.error || consent.error || complete.error}
      />
      {notice && (
        <p
          role="status"
          className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-800"
        >
          {notice}
        </p>
      )}
      {query.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="rounded-2xl border border-violet-200 bg-violet-50 p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-violet-900">
              <HeartHandshake size={18} />
              Research companion · synthetic demonstration
            </div>
            <p className="mt-2 text-sm leading-relaxed text-violet-800">
              This workspace displays your linked synthetic record and care-team
              tasks. It does not provide glucose forecasts, medication
              instructions, or an emergency-response service.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Latest recorded glucose"
              value={
                <>
                  {number(last?.glucose_mg_dl ?? last?.glucose, 0)}{" "}
                  <span className="text-sm font-normal">mg/dL</span>
                </>
              }
              note={
                last
                  ? timestamp(String(last.timestamp || last.observed_at))
                  : "No reading yet"
              }
            />
            <Metric
              label="Care-team tasks"
              value={d?.tasks.filter((t) => !t.completed_at).length ?? 0}
              note="Published for your record"
            />
            <Metric
              label="Research collection"
              value={granted ? "Granted" : "Not granted"}
              note="You can change your preference"
            />
          </div>
          <div className="grid items-start gap-5 lg:grid-cols-2">
            <Section
              title="Your care-team tasks"
              kicker="Published, never automatically invented"
            >
              {d?.tasks.length ? (
                <div className="space-y-4">
                  {d.tasks.map((t) => (
                    <div
                      key={String(t.id)}
                      className="rounded-xl border border-slate-200 p-4"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-base font-semibold text-slate-800">
                          {String(t.title)}
                        </h3>
                        <Chip
                          tone={Boolean(t.completed_at) ? "teal" : "neutral"}
                        >
                          {t.completed_at ? "Completed" : "Open"}
                        </Chip>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed text-slate-600">
                        {String(t.instructions || "")}
                      </p>
                      {Boolean(t.due_at) && (
                        <p className="mt-2 text-xs text-slate-500">
                          Due {timestamp(String(t.due_at))}
                        </p>
                      )}
                      {!t.completed_at && (
                        <button
                          className={outline + " mt-3"}
                          disabled={complete.isPending}
                          onClick={() => complete.mutate(String(t.id))}
                        >
                          <ClipboardCheck size={16} />
                          Mark completed
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No published tasks">
                  Your care team’s instructions will appear here after they
                  publish them.
                </Empty>
              )}
            </Section>
            <Section title="Share what happened" kicker="Self-reported context">
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  context.mutate();
                }}
              >
                <Field label="Context type">
                  <select
                    className={input}
                    value={kind}
                    onChange={(e) => setKind(e.target.value)}
                  >
                    {["meal", "activity", "symptom"].map((k) => (
                      <option key={k} value={k}>
                        {human(k)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="When did it happen?"
                  hint="Enter your device’s local time; saved with an explicit timezone."
                >
                  <input
                    type="datetime-local"
                    className={input}
                    value={at}
                    onChange={(e) => setAt(e.target.value)}
                    required
                  />
                </Field>
                <Field
                  label="Your note"
                  hint="Context is descriptive. It does not automatically change a forecast."
                >
                  <textarea
                    className={input + " min-h-28"}
                    required
                    maxLength={4000}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    placeholder="For example, a meal or activity you want your care team to know about."
                  />
                </Field>
                <button
                  className={solid + " w-full"}
                  disabled={context.isPending}
                >
                  <Check size={16} />
                  {context.isPending ? "Saving…" : "Share context"}
                </button>
              </form>
            </Section>
          </div>
          <Section title="Research collection preference" kicker="Your control">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {granted
                    ? "Research collection is granted"
                    : "Research collection is not granted"}
                </p>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500">
                  Withdrawing collection prevents new source collection under
                  this research preference. Existing audit records follow the
                  retention policy; this is not a claim that records are
                  immediately deleted.
                </p>
              </div>
              {granted ? (
                <button className={outline} onClick={() => setWithdraw(true)}>
                  Withdraw collection
                </button>
              ) : (
                <button
                  className={solid}
                  disabled={consent.isPending}
                  onClick={() => consent.mutate("grant")}
                >
                  Grant research collection
                </button>
              )}
            </div>
          </Section>
          <Section title="Your recent context">
            <div className="space-y-3">
              {d?.contexts.length ? (
                d.contexts
                  .slice(-8)
                  .reverse()
                  .map((c, i) => (
                    <div
                      key={String(c.id || i)}
                      className="border-b border-slate-100 pb-3 last:border-0"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {human(c.kind)}{" "}
                        <span className="ml-2 text-xs font-normal text-slate-500">
                          {c.provenance === "clinician_approved"
                            ? "Clinician approved"
                            : "Self-reported"}
                        </span>
                      </p>
                      <p className="mt-1 text-sm text-slate-600">
                        {typeof c.value === "object"
                          ? JSON.stringify(c.value)
                          : String(c.value || "")}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {timestamp(String(c.observed_at || c.timestamp || ""))}
                      </p>
                    </div>
                  ))
              ) : (
                <p className="text-sm text-slate-500">
                  Your shared context will appear here.
                </p>
              )}
            </div>
          </Section>
        </>
      )}
      <Modal
        open={withdraw}
        setOpen={setWithdraw}
        title="Withdraw research collection?"
        description="New collection for this research purpose will stop. Your retained record and care-team tasks remain visible."
      >
        <div className="flex gap-3">
          <button
            className={outline + " flex-1"}
            onClick={() => setWithdraw(false)}
          >
            Keep current preference
          </button>
          <button
            className={solid + " flex-1"}
            disabled={consent.isPending}
            onClick={() => consent.mutate("withdraw")}
          >
            Withdraw collection
          </button>
        </div>
      </Modal>
    </div>
  );
}

export function PublishTask({ patientId }: { patientId: string }) {
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [done, setDone] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      post("/v2/platform/tasks", {
        patient_id: patientId,
        title,
        instructions,
        published: true,
      }),
    onSuccess: () => {
      setDone(true);
      setTitle("");
      setInstructions("");
    },
  });
  return (
    <Section
      title="Publish a companion task"
      kicker="Clinician-authored instructions"
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Task title">
          <input
            className={input}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </Field>
        <Field label="Instructions">
          <textarea
            className={input + " min-h-24"}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            required
            maxLength={2000}
          />
        </Field>
        <ErrorBox error={mutation.error} />
        <button className={solid + " w-full"} disabled={mutation.isPending}>
          <Check size={16} />
          Publish for linked patient
        </button>
        {done && (
          <p role="status" className="text-sm text-teal-700">
            Task published to the patient’s companion.
          </p>
        )}
      </form>
    </Section>
  );
}

export function ShareApprovedNote({ patientId }: { patientId: string }) {
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      post("/v2/platform/shared-notes", { patient_id: patientId, note }),
    onSuccess: () => setNote(""),
  });
  return (
    <Section
      title="Share an approved note"
      kicker="Patient-visible, explicitly published"
    >
      <p className="mb-4 text-sm leading-relaxed text-slate-500">
        This note appears in the linked patient’s companion and summary. Private
        review notes remain separate.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Patient-visible note">
          <textarea
            aria-label="Patient-visible note"
            className={input + " min-h-24"}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            required
            maxLength={2000}
          />
        </Field>
        <ErrorBox error={mutation.error} />
        <button className={solid + " w-full"} disabled={mutation.isPending}>
          Publish approved note
        </button>
        {mutation.isSuccess && (
          <p role="status" className="text-sm text-teal-700">
            Approved note shared with this patient.
          </p>
        )}
      </form>
    </Section>
  );
}

export function AccountSecurity() {
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [otp, setOtp] = useState("");
  const setup = useMutation({
    mutationFn: () =>
      post<{ secret: string; uri: string }>("/v2/auth/mfa/setup", {}),
    onSuccess: (r) => {
      setSecret(r.secret);
      setUri(r.uri);
    },
  });
  const confirm = useMutation({
    mutationFn: () => post("/v2/auth/mfa/confirm", { otp }),
    onSuccess: () => {
      setSecret("");
      setUri("");
      setOtp("");
    },
  });
  return (
    <>
      <button
        className={outline + " mt-3 w-full"}
        onClick={() => setOpen(true)}
      >
        <ShieldCheck size={15} />
        Account security
      </button>
      <Modal
        open={open}
        setOpen={(v) => {
          setOpen(v);
          if (!v) {
            setSecret("");
            setUri("");
            setOtp("");
          }
        }}
        title="Protect your workspace account"
        description="Set up a time-based authenticator for your own account. The setup secret is displayed privately and must stay out of recordings."
      >
        {confirm.isSuccess ? (
          <p
            role="status"
            className="rounded-xl bg-teal-50 p-4 text-sm text-teal-800"
          >
            Two-factor authentication enabled. Your next sign-in requires a
            current authenticator code.
          </p>
        ) : secret ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              confirm.mutate();
            }}
          >
            <Field label="Authenticator secret">
              <input
                aria-label="Authenticator secret"
                className={input + " font-mono"}
                value={secret}
                readOnly
              />
            </Field>
            <Field label="Authenticator URI">
              <input className={input + " text-xs"} value={uri} readOnly />
            </Field>
            <Field label="Current six-digit code">
              <input
                className={input}
                aria-label="Verification code"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                required
                pattern="[0-9]{6}"
                inputMode="numeric"
                autoComplete="one-time-code"
              />
            </Field>
            <ErrorBox error={confirm.error} />
            <button className={solid + " w-full"} disabled={confirm.isPending}>
              Verify and enable
            </button>
          </form>
        ) : (
          <>
            <p className="mb-4 text-sm leading-relaxed text-slate-500">
              Use a compatible authenticator application. If two-factor
              authentication is already enabled, contact your clinic
              administrator for recovery.
            </p>
            <ErrorBox error={setup.error} />
            <button
              className={solid + " w-full"}
              disabled={setup.isPending}
              onClick={() => setup.mutate()}
            >
              Begin authenticator setup
            </button>
          </>
        )}
      </Modal>
    </>
  );
}
