import { useEffect, useMemo, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  Clock3,
  Download,
  FileCheck2,
  Filter,
  Fingerprint,
  FlaskConical,
  LockKeyhole,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PublishTask, ShareApprovedNote } from "./PlatformViews";
import { api, download, post } from "./api";
import type {
  Benchmark,
  Monitoring,
  Patient,
  QueueData,
  ReviewItem,
  Snapshot,
  TimelineEvent,
  User,
} from "./types";
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
  number,
  outline,
  percentage,
  Section,
  solid,
  surface,
  timestamp,
} from "./Design";

export type ClinicReview = ReviewItem & {
  revision?: number;
  disposition?: string;
  latest_forecast_id?: string;
  current_quality?: {
    status: string;
    last_reading_at?: string;
    last_received_at?: string;
    minutes_since_reading?: number;
  };
  source_status?: string;
};
export interface Receipt {
  id: string;
  patient_id: string;
  patient?: Patient;
  issued_at: string;
  input_cutoff?: string;
  model_version?: string;
  source_connection_id?: string;
  input_digest?: string;
  clock_kind?: string;
  snapshot: Snapshot;
  outcomes?: {
    horizon_minutes: number;
    target_time: string;
    available_at?: string;
    actual_glucose_mg_dl: number;
    event_occurred?: boolean;
  }[];
  review_id?: string;
}
export type V2Queue = Omit<QueueData, "items"> & {
  items: ClinicReview[];
  server_time?: string;
  mode?: string;
};
export function usePatients() {
  return useQuery({
    queryKey: ["patients"],
    queryFn: () => api<Patient[]>("/patients"),
  });
}
export function MonitoringStatus({
  monitoring,
}: {
  monitoring?: Monitoring | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 text-sm">
        <span
          className={
            "h-2 w-2 rounded-full " +
            (monitoring?.active ? "bg-teal-600" : "bg-amber-500")
          }
        />
        <strong className="font-semibold text-slate-700">
          {monitoring?.active
            ? "Staffed window active"
            : "Outside staffed monitoring"}
        </strong>
        <span className="hidden text-slate-500 sm:inline">
          {monitoring
            ? String(monitoring.start_hour).padStart(2, "0") +
              ":00–" +
              String(monitoring.end_hour).padStart(2, "0") +
              ":00 · " +
              monitoring.timezone
            : "Configuration not yet available"}
        </span>
      </div>
      <span className="text-xs text-slate-500">
        Responsible: {monitoring?.reviewer_id || "Unassigned"}
        {monitoring?.clock_kind === "recorded" ? " · recorded clock" : ""}
      </span>
    </div>
  );
}

export function ReviewDesk({ user }: { user: User }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("search") || "");
  const query = useQuery({
    queryKey: ["queue"],
    queryFn: () => api<V2Queue>("/v2/queue"),
    refetchInterval: 15000,
  });
  const patients = usePatients();
  const benchmark = useQuery({
    queryKey: ["clinic-benchmark"],
    queryFn: () => api<Benchmark>("/clinic-benchmark"),
  });
  const filter = params.get("filter") || "mine";
  const items = (query.data?.items || [])
    .filter((item) => {
      const match = (
        item.patient_name +
        " " +
        item.patient_id +
        " " +
        item.message
      )
        .toLowerCase()
        .includes(search.toLowerCase());
      return (
        match &&
        (filter === "all" ||
          (filter === "mine" &&
            (item.assigned_reviewer === user.username ||
              item.assigned_reviewer === user.id) &&
            item.status !== "closed") ||
          (filter === "unassigned" &&
            !item.assigned_reviewer &&
            item.status !== "closed") ||
          (filter === "overdue" && item.overdue) ||
          (filter === "data" &&
            ["sensor_gap", "missing_data"].includes(item.type)) ||
          (filter === "closed" && item.status === "closed"))
      );
    })
    .sort(
      (a, b) =>
        Number(!!b.overdue) - Number(!!a.overdue) ||
        Number(a.status === "closed") - Number(b.status === "closed") ||
        a.issued_at.localeCompare(b.issued_at),
    );
  const demo = benchmark.data?.demo;
  const openDemo = () =>
    navigate(
      "/patients/" +
        (demo?.patient_id || patients.data?.[0]?.id || "2072") +
        "?mode=replay&cursor=" +
        (demo?.warning_cursor ?? demo?.cursor ?? 853),
    );
  return (
    <div className="space-y-6">
      <Heading
        overline="Your review desk"
        title="Make every signal accountable."
        actions={
          <button className={solid} onClick={openDemo}>
            <Play size={16} />
            Open recorded demonstration
          </button>
        }
      >
        One place to inspect evidence, document a next step, and follow the
        outcome.
      </Heading>
      <MonitoringStatus monitoring={query.data?.monitoring} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          label="Awaiting review"
          value={query.data?.pending_count ?? "—"}
          note="Open care-team episodes"
        />
        <Metric
          label="Follow-up overdue"
          value={query.data?.overdue_count ?? "—"}
          tone={(query.data?.overdue_count || 0) > 0 ? "amber" : "neutral"}
          note="Requires a documented next step"
        />
        <Metric
          label="Patients with episodes"
          value={
            new Set((query.data?.items || []).map((x) => x.patient_id)).size
          }
          note="Distinct patients in saved review records"
        />
      </div>
      <ErrorBox error={query.error} retry={() => void query.refetch()} />
      <div className={surface + " overflow-hidden"}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-[200px] flex-1 sm:max-w-sm">
            <Search
              className="absolute left-3 top-3.5 text-slate-400"
              size={16}
            />
            <input
              className={input + " !pl-10"}
              aria-label="Search review queue"
              placeholder="Search patient or review reason"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setParams(
                  { ...Object.fromEntries(params), search: e.target.value },
                  { replace: true },
                );
              }}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="queue-filter">
              Queue filter
            </label>
            <Filter size={16} className="text-slate-400" />
            <select
              id="queue-filter"
              className={input + " !w-auto"}
              value={filter}
              onChange={(e) =>
                setParams({
                  ...Object.fromEntries(params),
                  filter: e.target.value,
                })
              }
            >
              {[
                ["mine", "Assigned to me"],
                ["all", "All episodes"],
                ["unassigned", "Unassigned"],
                ["overdue", "Overdue follow-up"],
                ["data", "Data issues"],
                ["closed", "Closed"],
              ].map(([id, title]) => (
                <option key={id} value={id}>
                  {title}
                </option>
              ))}
            </select>
            <button
              className={outline + " !px-3"}
              onClick={() => void query.refetch()}
              aria-label="Refresh queue"
            >
              <RefreshCw size={17} />
            </button>
          </div>
        </div>
        {query.isPending ? (
          <Loading label="Loading review episodes…" />
        ) : items.length ? (
          <div>
            {items.map((item) => (
              <Link
                key={item.id}
                to={
                  "/patients/" +
                  item.patient_id +
                  "?review=" +
                  item.id +
                  (item.forecast_id ? "&receipt=" + item.forecast_id : "")
                }
                className="group grid gap-3 border-b border-slate-100 p-5 outline-none transition-colors last:border-0 hover:bg-slate-50 focus-visible:bg-teal-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600 md:grid-cols-[minmax(0,1fr)_160px_160px_28px]"
              >
                <div className="flex items-start gap-3">
                  <div
                    className={
                      "mt-0.5 rounded-xl p-2.5 " +
                      (["missing_data", "sensor_gap"].includes(item.type)
                        ? "bg-slate-100 text-slate-500"
                        : "bg-amber-50 text-amber-700")
                    }
                  >
                    <Activity size={18} />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-900">
                        {item.patient_name || "Patient " + item.patient_id}
                      </p>
                      <Chip tone={item.overdue ? "amber" : "neutral"}>
                        {item.overdue
                          ? "Follow-up overdue"
                          : human(item.status)}
                      </Chip>
                    </div>
                    <p className="mt-1 text-sm text-slate-600">
                      {human(item.type)}
                    </p>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                      {item.message ||
                        "Inspect the saved evidence and review history."}
                    </p>
                  </div>
                </div>
                <div className="pl-12 md:pl-0">
                  <p className="text-xs text-slate-500">At issue</p>
                  <p className="mt-1 text-sm font-medium text-slate-700">
                    {percentage(item.probability)} excursion probability
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {timestamp(
                      item.issued_at,
                      item.patient_id.startsWith("SIM-")
                        ? "Asia/Kolkata"
                        : "recorded",
                    )}
                  </p>
                </div>
                <div className="pl-12 md:pl-0">
                  <p className="text-xs text-slate-500">Responsible reviewer</p>
                  <p className="mt-1 text-sm font-medium text-slate-700">
                    {item.assigned_reviewer || "Unassigned"}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {item.current_quality
                      ? human(item.current_quality.status) +
                        " · received " +
                        timestamp(item.current_quality.last_received_at)
                      : "Recorded receipt · historical freshness"}
                  </p>
                </div>
                <ChevronRight
                  size={20}
                  className="hidden self-center text-slate-400 group-hover:text-teal-700 md:block"
                />
              </Link>
            ))}
          </div>
        ) : (
          <Empty
            title={
              filter === "mine" ? "Your queue is clear" : "No matching episodes"
            }
            action={
              <button className={outline} onClick={openDemo}>
                Explore a recorded case
                <ArrowRight size={16} />
              </button>
            }
          >
            Newly issued warning episodes appear here. A clear queue does not
            establish that a patient is clinically safe.
          </Empty>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="A twin you can inspect" kicker="The evidence loop">
          <div className="flex flex-wrap gap-2">
            {[
              "Available readings",
              "Issued forecast",
              "Clinician review",
              "Observed outcome",
              "Matured update",
            ].map((v, i) => (
              <div key={v} className="flex items-center gap-2">
                <Chip tone={i === 1 ? "teal" : "neutral"}>{v}</Chip>
                {i < 4 && <ChevronRight size={13} className="text-slate-400" />}
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm leading-relaxed text-slate-500">
            Every prediction has a time boundary. Every review retains its own
            history.
          </p>
        </Section>
        <Section
          title="Connected research, clearly labeled"
          kicker="Deployment boundary"
        >
          <p className="text-sm leading-relaxed text-slate-500">
            Recorded public CGM and a continuous generated synthetic stream
            demonstrate the workflow. An authorized clinical CGM connection and
            prospective clinical validation remain pending.
          </p>
          <Link className={outline + " mt-4"} to="/operations">
            Inspect source and service status
            <ArrowRight size={16} />
          </Link>
        </Section>
      </div>
    </div>
  );
}

function activeModel(snapshot: Snapshot | null): Snapshot | null {
  if (!snapshot?.clinic_model) return snapshot;
  const c = snapshot.clinic_model;
  return {
    ...snapshot,
    model: c.model,
    event_risks: c.event_risks,
    adaptation: c.adaptation,
    forecasts: {
      ...c.forecasts,
      twin:
        c.model.primary === "hybrid"
          ? c.forecasts.hybrid
          : c.forecasts.population,
    },
    forecast_history: (c.forecast_history || []).map((r) => ({
      issued_at: r.issued_at,
      target_time: r.target_at,
      horizon_minutes: r.horizon_minutes,
      twin: c.model.primary === "hybrid" ? r.hybrid_mg_dl : r.population_mg_dl,
      population: r.population_mg_dl,
      actual: r.actual_mg_dl,
    })),
  };
}
function ForecastChart({
  snapshot,
  lens,
  receipt,
}: {
  snapshot: Snapshot;
  lens: boolean;
  receipt?: Receipt;
}) {
  const [table, setTable] = useState(false);
  const arrival = receipt?.clock_kind === "server_received";
  const zone = arrival ? "Asia/Kolkata" : "recorded";
  const epoch = (value: string) =>
    new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + "Z").getTime();
  const thirty = snapshot.forecasts.twin?.find((x) => x.horizon_minutes === 30);
  const observed = snapshot.observations.slice(-32);
  const rows = [
    ...observed.map((o) => ({
      time: o.timestamp,
      at: epoch(o.timestamp),
      observed: o.glucose_mg_dl,
      forecast: null as number | null,
      population: null as number | null,
      band: null as [number, number] | null,
    })),
    ...snapshot.forecasts.twin.map((f) => ({
      time: f.timestamp,
      at: epoch(f.timestamp),
      observed: null as number | null,
      forecast: f.glucose_mg_dl,
      population:
        snapshot.forecasts.population?.find(
          (p) => p.horizon_minutes === f.horizon_minutes,
        )?.glucose_mg_dl ?? null,
      band:
        f.lower !== null && f.upper !== null
          ? ([f.lower, f.upper] as [number, number])
          : null,
    })),
  ];
  if (rows.length && snapshot.forecasts.twin.length) {
    const last = rows[observed.length - 1];
    last.forecast = last.observed;
    last.population = last.observed;
  }
  const cutoff = receipt?.input_cutoff || snapshot.current_time;
  const clock = (v: number) =>
    new Date(v).toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: arrival ? "Asia/Kolkata" : "UTC",
    });
  return (
    <Section
      title="Glucose trajectory"
      kicker="Observed → available → forecast"
      actions={
        <button
          className={outline}
          onClick={() => setTable(!table)}
          aria-expanded={table}
        >
          {table ? "Hide data table" : "Show data table"}
        </button>
      }
    >
      <p className="mb-4 text-sm leading-relaxed text-slate-500">
        {thirty
          ? "30-minute forecast " +
            number(thirty.glucose_mg_dl, 0) +
            " mg/dL; interval " +
            number(thirty.lower, 0) +
            "–" +
            number(thirty.upper, 0) +
            " mg/dL."
          : "Forecast withheld; inspect data eligibility."}{" "}
        Observed values are solid; forecasts are dashed. The shaded band is a
        {arrival
          ? "research interval whose coverage is unvalidated for arrival mode."
          : "predictive interval from retrospective calibration."}
      </p>
      <div
        className="h-[290px] w-full sm:h-[340px]"
        role="img"
        aria-label="Observed glucose and issued forecasts with uncertainty, exact values in data table"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 18, right: 12, left: -12, bottom: 8 }}
          >
            <CartesianGrid stroke="#e8edf1" vertical={false} />
            <XAxis
              dataKey="at"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={clock}
              tick={{ fill: "#64748b", fontSize: 12 }}
              minTickGap={70}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#64748b", fontSize: 12 }}
              domain={["auto", "auto"]}
              axisLine={false}
              tickLine={false}
              width={52}
            />
            <Tooltip
              labelFormatter={(v) =>
                timestamp(new Date(Number(v)).toISOString(), zone)
              }
              formatter={(v, name) => [
                Array.isArray(v)
                  ? v.map((x) => number(x, 0)).join("–") + " mg/dL"
                  : number(v, 0) + " mg/dL",
                human(name),
              ]}
              contentStyle={{
                borderRadius: 12,
                border: "1px solid #e2e8f0",
                fontSize: 14,
              }}
            />
            <ReferenceLine
              y={180}
              stroke="#d99b3f"
              strokeDasharray="5 5"
              label={{
                value: "Excursion definition · 180",
                position: "insideTopLeft",
                fontSize: 12,
                fill: "#976323",
              }}
            />
            <ReferenceLine
              x={epoch(cutoff)}
              stroke="#94a3b8"
              strokeDasharray="3 3"
              label={{
                value: lens ? "INPUT CUTOFF" : "NOW",
                position: "insideTopRight",
                fontSize: 12,
                fill: "#64748b",
              }}
            />
            <Area
              dataKey="band"
              stroke="none"
              fill="#0f766e"
              fillOpacity={0.1}
              isAnimationActive={false}
            />
            <Line
              dataKey="observed"
              stroke="#193748"
              strokeWidth={2.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="forecast"
              stroke="#0d9488"
              strokeWidth={2.5}
              strokeDasharray="5 4"
              dot={{ r: 3 }}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="population"
              stroke="#8b5cf6"
              strokeWidth={1.8}
              strokeDasharray="2 4"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-500">
        {[
          ["bg-slate-700", "Measured glucose"],
          ["bg-teal-600", "Active forecast"],
          ["bg-violet-500", "Population comparison"],
          ["bg-teal-100", "Predictive interval"],
        ].map(([color, title]) => (
          <span key={title} className="flex items-center gap-2">
            <span className={"h-2 w-5 rounded " + color} />
            {title}
          </span>
        ))}
      </div>
      {lens && (
        <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-violet-900">
            <LockKeyhole size={16} />
            What the model knew
          </p>
          <p className="mt-2 text-sm leading-relaxed text-violet-800">
            Only readings available by {timestamp(cutoff, zone)} enter this
            forecast. Observation time and arrival time are shown separately.
            Self-reported context is descriptive unless its predictive
            contribution has been evaluated.
          </p>
          <div className="mt-3 space-y-2">
            {(
              (receipt?.snapshot.observations || observed)
                .filter(
                  (o) =>
                    epoch(
                      (o as { available_at?: string }).available_at ||
                        o.timestamp,
                    ) <= epoch(cutoff),
                )
                .slice(-3) as ((typeof observed)[number] & {
                available_at?: string;
              })[]
            ).map((o) => (
              <p key={o.timestamp} className="text-xs text-violet-700">
                Observed {timestamp(o.timestamp, zone)} · Available{" "}
                {timestamp(o.available_at || o.timestamp, zone)} ·{" "}
                {number(o.glucose_mg_dl)} mg/dL
              </p>
            ))}
          </div>
        </div>
      )}
      {table && (
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[540px] text-left text-sm">
            <caption className="sr-only">Trajectory data in mg/dL</caption>
            <thead className="bg-slate-50">
              <tr>
                {[
                  "Timestamp",
                  "Measured",
                  "Active forecast",
                  "Population",
                  "Interval",
                ].map((h) => (
                  <th key={h} className="px-3 py-3 font-medium text-slate-600">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(-14).map((r, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-3 py-3 text-xs">
                    {timestamp(r.time, zone)}
                  </td>
                  <td className="px-3 py-3">{number(r.observed)}</td>
                  <td className="px-3 py-3">{number(r.forecast)}</td>
                  <td className="px-3 py-3">{number(r.population)}</td>
                  <td className="px-3 py-3">
                    {r.band ? r.band.map((v) => number(v, 0)).join("–") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

export function CareAction({
  item,
  user,
}: {
  item?: ClinicReview;
  user: User;
}) {
  const client = useQueryClient();
  const [status, setStatus] = useState("reviewed");
  const [reason, setReason] = useState("evidence_reviewed");
  const [note, setNote] = useState("");
  const [next, setNext] = useState("");
  const [assigned, setAssigned] = useState("");
  const [disposition, setDisposition] = useState("reviewed_no_action");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    setNote(
      item ? sessionStorage.getItem("glucotwin.draft." + item.id) || "" : "",
    );
    setAssigned(item?.assigned_reviewer || "");
    setStatus(
      item?.status === "follow_up_planned"
        ? "closed"
        : item?.status === "reviewed"
          ? "follow_up_planned"
          : "reviewed",
    );
    setNext("");
  }, [item?.id, item?.status]);
  const detail = useQuery({
    queryKey: ["review", item?.id],
    queryFn: () => api<ClinicReview>("/clinic/reviews/" + item?.id),
    enabled: !!item,
  });
  const mutation = useMutation({
    mutationFn: (body: object) =>
      post<ClinicReview>("/v2/reviews/" + item?.id, body, "PATCH"),
    onSuccess: () => {
      if (item) sessionStorage.removeItem("glucotwin.draft." + item.id);
      setNote("");
      setSaved("Review saved to the audit history.");
      void client.invalidateQueries({ queryKey: ["queue"] });
      void client.invalidateQueries({ queryKey: ["review", item?.id] });
      void client.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
  const base = {
    expected_revision: item?.revision ?? detail.data?.revision,
    reason,
    assigned_reviewer: assigned || user.username,
  };
  return (
    <Section
      title="Clinician review"
      kicker="An accountable next step"
      className="lg:sticky lg:top-24"
    >
      <div className="flex items-center gap-2">
        <ShieldCheck size={18} className="text-teal-700" />
        <span className="text-sm font-medium text-slate-700">
          {user.name || user.username}
        </span>
      </div>
      {!item ? (
        <Empty title="No episode selected">
          Pin or save a forecast to begin a review. Acknowledging a warning
          never changes the model’s accuracy.
        </Empty>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-2">
            <Chip tone={item.status === "new" ? "amber" : "teal"}>
              {human(item.status)}
            </Chip>
            <Chip>Revision {item.revision ?? detail.data?.revision ?? 1}</Chip>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            {human(item.type)} · Episode {String(item.id).slice(0, 12)}
          </p>
          <div className="mt-4 space-y-3">
            <Field label="Assigned reviewer">
              <input
                aria-label="Assigned reviewer"
                className={input}
                value={assigned}
                onChange={(e) => setAssigned(e.target.value)}
              />
            </Field>
            <button
              className={outline + " w-full"}
              disabled={mutation.isPending}
              onClick={() =>
                mutation.mutate({
                  ...base,
                  assigned_reviewer: user.username,
                  reason: "Reviewer claimed the episode",
                })
              }
            >
              <UserRound size={16} />
              Assign to me
            </button>
          </div>
          {item.status === "closed" ? (
            <div className="mt-5 rounded-xl bg-teal-50 p-4 text-sm text-teal-900">
              This episode is closed. Its prediction and review history remain
              available.
            </div>
          ) : (
            <form
              className="mt-5 space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                mutation.mutate({
                  ...base,
                  status,
                  note,
                  disposition,
                  next_review_at: next ? new Date(next).toISOString() : null,
                });
              }}
            >
              <Field label="Next state">
                <select
                  className={input}
                  aria-label="Review status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  {(item.status === "new"
                    ? ["reviewed"]
                    : item.status === "reviewed"
                      ? ["follow_up_planned", "closed"]
                      : ["closed"]
                  ).map((s) => (
                    <option key={s} value={s}>
                      {human(s)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Disposition">
                <select
                  className={input}
                  aria-label="Review disposition"
                  value={disposition}
                  onChange={(e) => setDisposition(e.target.value)}
                >
                  {[
                    "reviewed_no_action",
                    "context_requested",
                    "follow_up_scheduled",
                    "technical_issue",
                    "closed_after_review",
                  ].map((s) => (
                    <option key={s} value={s}>
                      {human(s)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Reason">
                <select
                  className={input}
                  aria-label="Review reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                >
                  {[
                    "evidence_reviewed",
                    "patient_contact_planned",
                    "data_quality_follow_up",
                    "no_action_required",
                    "other",
                  ].map((s) => (
                    <option key={s} value={s}>
                      {human(s)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Decision note"
                hint="A private draft is retained in this browser tab until saved or signed out."
              >
                <textarea
                  className={input + " min-h-28"}
                  aria-label="Decision note"
                  value={note}
                  maxLength={4000}
                  required
                  onChange={(e) => {
                    setNote(e.target.value);
                    sessionStorage.setItem(
                      "glucotwin.draft." + item.id,
                      e.target.value,
                    );
                  }}
                  placeholder="Document the evidence and your next step."
                />
              </Field>
              <Field
                label={
                  status === "follow_up_planned"
                    ? "Next review (required)"
                    : "Next review (optional)"
                }
                hint="Entered in this device’s local timezone; stored with an explicit timezone."
              >
                <input
                  className={input}
                  type="datetime-local"
                  aria-label="Next review time"
                  value={next}
                  required={status === "follow_up_planned"}
                  onChange={(e) => setNext(e.target.value)}
                />
              </Field>
              <ErrorBox error={mutation.error} />
              <button
                className={solid + " w-full"}
                disabled={mutation.isPending || !navigator.onLine}
              >
                <Check size={16} />
                {mutation.isPending ? "Saving review…" : "Record review"}
              </button>
            </form>
          )}
          {saved && (
            <p role="status" className="mt-3 text-sm text-teal-700">
              {saved}
            </p>
          )}
          {!!detail.data?.actions?.length && (
            <div className="mt-5 border-t border-slate-100 pt-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Audit history
              </p>
              <ol className="mt-3 space-y-3">
                {detail.data.actions.map((a, i) => (
                  <li key={a.id || i} className="rounded-xl bg-slate-50 p-3">
                    <p className="text-sm font-medium text-slate-700">
                      {human(a.status)}
                    </p>
                    <p className="mt-1 text-sm text-slate-600">{a.note}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {a.reviewer || a.reviewer_id || a.actor_id} ·{" "}
                      {timestamp(a.recorded_at || a.created_at || a.timestamp)}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </Section>
  );
}

export function PatientWorkspace({ user }: { user: User }) {
  const { patientId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const [playing, setPlaying] = useState(false);
  const [lens, setLens] = useState(false);
  const [notice, setNotice] = useState("");
  const patients = usePatients();
  const patient = patients.data?.find((p) => p.id === patientId);
  const mode =
    params.get("mode") || (patientId.startsWith("SIM-") ? "feed" : "replay");
  const cursor = Number(params.get("cursor") || 96);
  const scenario = params.get("scenario") || "recorded";
  const receiptId = params.get("receipt");
  const receiptList = useQuery({
    queryKey: ["receipts", patientId],
    queryFn: () =>
      api<{ items: Receipt[]; total: number }>(
        "/v2/patients/" + encodeURIComponent(patientId) + "/receipts",
      ),
    refetchInterval: mode === "feed" ? 10000 : false,
  });
  const selectedId =
    receiptId || (mode === "feed" ? receiptList.data?.items[0]?.id : undefined);
  const receiptQuery = useQuery({
    queryKey: ["receipt", selectedId],
    queryFn: () => api<Receipt>("/v2/receipts/" + selectedId),
    enabled: !!selectedId,
    refetchInterval: mode === "feed" ? 10000 : false,
  });
  const replay = useQuery({
    queryKey: ["replay", patientId, cursor, scenario],
    queryFn: () =>
      api<Snapshot>(
        "/replay/" +
          encodeURIComponent(patientId) +
          "?cursor=" +
          cursor +
          "&scenario=" +
          scenario,
      ),
    enabled: mode === "replay",
  });
  const snapshot = activeModel(
    mode === "replay"
      ? replay.data || null
      : receiptQuery.data?.snapshot || null,
  );
  const queue = useQuery({
    queryKey: ["queue"],
    queryFn: () => api<V2Queue>("/v2/queue"),
    refetchInterval: 15000,
  });
  const review =
    queue.data?.items.find((i) => String(i.id) === params.get("review")) ||
    queue.data?.items.find(
      (i) => i.patient_id === patientId && i.status !== "closed",
    ) ||
    queue.data?.items.find((i) => i.patient_id === patientId);
  const timeline = useQuery({
    queryKey: ["timeline", patientId, snapshot?.current_time, scenario],
    queryFn: () =>
      api<{ events: TimelineEvent[] }>(
        "/clinic/timeline/" +
          encodeURIComponent(patientId) +
          "?at=" +
          encodeURIComponent(snapshot?.current_time || "") +
          "&scenario=" +
          scenario,
      ),
    enabled: !!snapshot,
  });
  const capture = useMutation({
    mutationFn: () =>
      post<{ forecast_id: string; review_id?: string }>(
        "/v2/replay/capture/" + encodeURIComponent(patientId),
        {
          cursor,
          scenario,
          ...(patientId.startsWith("SIM-") && snapshot
            ? { current_time: snapshot.current_time }
            : {}),
        },
      ),
    onSuccess: (r) => {
      setPlaying(false);
      setNotice("Forecast issued and saved with its original evidence.");
      setParams({
        ...Object.fromEntries(params),
        receipt: String(r.forecast_id),
        ...(r.review_id ? { review: String(r.review_id) } : {}),
      });
      void client.invalidateQueries({ queryKey: ["queue"] });
      void client.invalidateQueries({ queryKey: ["receipts", patientId] });
      void client.invalidateQueries({ queryKey: ["receipt"] });
      void client.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
  useEffect(() => {
    setPlaying(false);
    setNotice("");
  }, [patientId, mode]);
  useEffect(() => {
    if (!playing || !snapshot) return;
    const timer = setInterval(() => {
      if (cursor >= snapshot.total_observations - 1) setPlaying(false);
      else
        setParams(
          { ...Object.fromEntries(params), cursor: String(cursor + 1) },
          { replace: true },
        );
    }, 1500);
    return () => clearInterval(timer);
  }, [playing, cursor, snapshot, params, setParams]);
  const thirty = snapshot?.forecasts.twin?.find(
    (f) => f.horizon_minutes === 30,
  );
  const risk = snapshot?.event_risks?.find((r) => r.horizon_minutes === 30);
  const signalEligible = mode !== "feed" || risk?.warning_supported !== false;
  const flagged =
    !!risk?.exceeds_threshold &&
    signalEligible &&
    (mode !== "feed" || risk?.research_review_eligible !== false);
  const last = snapshot?.observations.at(-1);
  const quality = snapshot?.quality.status || "unavailable";
  const adaptation = snapshot?.adaptation;
  const bad = [
    "gap",
    "warming_up",
    "unavailable",
    "stale",
    "unsupported_cadence",
    "irregular_cadence",
  ].includes(quality);
  const source = patientId.startsWith("SIM-")
    ? receiptQuery.data?.source_connection_id
      ? "Generated synthetic stream"
      : "Synthetic research profile"
    : patientId.startsWith("PUB-")
      ? "Imported public data"
      : "Recorded ShanghaiT2DM";
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-500 hover:text-teal-700"
          to="/review"
        >
          <ArrowLeft size={16} />
          Back to review desk
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone={mode === "feed" ? "violet" : "neutral"}>
            <FlaskConical size={13} />
            {mode === "feed" ? "Research feed" : "Recorded playback"}
          </Chip>
          <Chip>{source}</Chip>
        </div>
      </div>
      <Heading
        overline="Patient twin workspace"
        title={
          patient?.display_name ||
          receiptQuery.data?.patient?.display_name ||
          "Patient " + patientId
        }
        actions={
          <>
            <button
              className={outline}
              onClick={() =>
                void download(
                  "/clinic/report/" +
                    encodeURIComponent(patientId) +
                    (mode === "replay" && snapshot
                      ? "?at=" +
                        encodeURIComponent(snapshot.current_time) +
                        "&scenario=" +
                        scenario
                      : ""),
                  "GlucoTwin_" + patientId + "_Consultation.pdf",
                ).catch((e) => setNotice(e.message))
              }
            >
              <Download size={16} />
              Consultation summary
            </button>
            {mode === "replay" && (
              <button
                className={solid}
                disabled={capture.isPending || !snapshot || bad || !thirty}
                onClick={() => capture.mutate()}
              >
                <FileCheck2 size={16} />
                Freeze forecast for review
              </button>
            )}
          </>
        }
      >
        Evidence is timestamped. A prediction is a research signal for review.
      </Heading>
      <div className="flex flex-wrap gap-2 text-sm text-slate-500">
        {patient?.age != null && <span>{number(patient.age, 0)} years</span>}
        {patient?.sex && <span>· {patient.sex}</span>}
        {patient?.bmi != null && <span>· BMI {number(patient.bmi)}</span>}
        <span>· {patientId}</span>
      </div>
      <MonitoringStatus
        monitoring={snapshot?.monitoring || queue.data?.monitoring}
      />
      {notice && (
        <p
          role="status"
          className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-800"
        >
          {notice}
        </p>
      )}
      <ErrorBox error={replay.error || receiptQuery.error || capture.error} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Latest observation"
              value={
                <>
                  {number(last?.glucose_mg_dl, 0)}{" "}
                  <span className="text-sm font-normal text-slate-500">
                    mg/dL
                  </span>
                </>
              }
              note={
                last
                  ? timestamp(
                      last.timestamp,
                      mode === "replay" ? "recorded" : "Asia/Kolkata",
                    )
                  : "Awaiting source data"
              }
            />
            <Metric
              label={
                mode === "feed"
                  ? "30-min measurement target"
                  : "30-minute forecast"
              }
              tone="teal"
              value={
                <>
                  {number(thirty?.glucose_mg_dl, 0)}{" "}
                  <span className="text-sm font-normal text-slate-500">
                    mg/dL
                  </span>
                </>
              }
              note={
                thirty
                  ? (mode === "feed"
                      ? "Unvalidated research interval "
                      : "Predictive interval ") +
                    number(thirty.lower, 0) +
                    "–" +
                    number(thirty.upper, 0) +
                    " mg/dL"
                  : "Withheld until observations support a forecast"
              }
            />
            <Metric
              label="New excursion probability"
              tone={flagged ? "amber" : "neutral"}
              value={
                risk?.ongoing_high
                  ? "Ongoing high"
                  : risk?.event_eligible && signalEligible
                    ? percentage(risk.probability)
                    : "Withheld"
              }
              note={
                risk?.event_eligible && signalEligible
                  ? (mode === "feed"
                      ? "Scheduled native targets after the latest measurement · point "
                      : "Any measured value >180 within 30 min · operating point ") +
                    percentage(risk.threshold)
                  : "Eligibility is separate from prediction accuracy"
              }
            />
          </div>
          {snapshot ? (
            <ForecastChart
              snapshot={snapshot}
              lens={lens}
              receipt={receiptQuery.data}
            />
          ) : receiptList.isPending ||
            (mode === "replay" && replay.isPending) ? (
            <Loading label="Preparing patient evidence…" />
          ) : (
            <Section title="Waiting for an issued forecast">
              <Empty title="No supported receipt yet">
                The monitoring worker creates a receipt when a source has enough
                eligible observations. A synthetic source is labeled throughout.
              </Empty>
            </Section>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4">
            <button
              className={
                outline +
                (lens
                  ? " !border-violet-300 !bg-violet-50 !text-violet-800"
                  : "")
              }
              onClick={() => setLens(!lens)}
              aria-pressed={lens}
            >
              <Sparkles size={16} />
              What the model knew
            </button>
            {mode === "replay" && (
              <div className="flex flex-wrap gap-2">
                <button
                  className={solid}
                  onClick={() => setPlaying(!playing)}
                  disabled={!snapshot}
                >
                  {playing ? <Pause size={16} /> : <Play size={16} />}{" "}
                  {playing ? "Pause" : "Play"} recorded data
                </button>
                <button
                  className={outline}
                  onClick={() => {
                    setPlaying(false);
                    setParams({
                      ...Object.fromEntries(params),
                      cursor: String(cursor + 1),
                    });
                  }}
                >
                  Next reading
                  <ArrowRight size={16} />
                </button>
                <button
                  className={outline}
                  onClick={() => {
                    setPlaying(false);
                    setParams({
                      ...Object.fromEntries(params),
                      scenario:
                        scenario === "sensor_gap" ? "recorded" : "sensor_gap",
                    });
                  }}
                >
                  <SlidersHorizontal size={16} />
                  {scenario === "sensor_gap"
                    ? "Restore recorded sensor"
                    : "Demonstrate sensor gap"}
                </button>
              </div>
            )}
          </div>
          {mode === "replay" && snapshot && (
            <div className="rounded-xl bg-slate-100/70 p-4">
              <label
                className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-slate-700"
                htmlFor="recorded-cursor"
              >
                <span>
                  Recorded clock · historical source timezone unverified
                </span>
                <span className="text-xs font-normal">
                  Reading {cursor + 1} / {snapshot.total_observations}
                </span>
              </label>
              <input
                id="recorded-cursor"
                className="mt-3 w-full accent-teal-700"
                type="range"
                min={0}
                max={snapshot.total_observations - 1}
                value={cursor}
                onChange={(e) => {
                  setPlaying(false);
                  setParams(
                    { ...Object.fromEntries(params), cursor: e.target.value },
                    { replace: true },
                  );
                }}
              />
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Data eligibility" kicker="Why forecast or abstain">
              <Chip tone={bad ? "amber" : "teal"}>{human(quality)}</Chip>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">
                {snapshot?.quality.message ||
                  "No eligible observation prefix is available."}
              </p>
              <p className="mt-3 text-xs text-slate-500">
                {mode === "replay"
                  ? "Freshness is evaluated at the historical playback clock. This is not live device health."
                  : "Observation age and arrival age are evaluated by the server. Source connection remains a research demonstration."}
              </p>
            </Section>
            <Section
              title="Visible adaptation"
              kicker="Outcome first, update second"
            >
              <p className="text-2xl font-semibold text-slate-900">
                {number(adaptation?.correction_mg_dl)}{" "}
                <span className="text-sm font-normal text-slate-500">
                  mg/dL correction
                </span>
              </p>
              <p className="mt-2 text-sm text-slate-600">
                {human(adaptation?.maturity)} ·{" "}
                {String(adaptation?.matured_samples ?? 0)} matured targets
              </p>
              <p className="mt-3 text-xs leading-relaxed text-slate-500">
                Patient correction changes only when an earlier outcome becomes
                observable. Clinical effectiveness is unestablished.
              </p>
            </Section>
          </div>
          {receiptQuery.data && (mode !== "replay" || snapshot) && (
            <ReceiptCard
              receipt={receiptQuery.data}
              visibleAt={mode === "replay" ? snapshot?.current_time : undefined}
            />
          )}
          <Section
            title="Evidence timeline"
            kicker="Observations, receipts, care actions"
          >
            <div className="mb-4 flex flex-wrap gap-2">
              <Chip tone="teal">Measured</Chip>
              <Chip tone="violet">Forecast</Chip>
              <Chip>Clinician review</Chip>
              <Chip tone="amber">Self-reported / simulated</Chip>
            </div>
            {timeline.isPending ? (
              <Loading />
            ) : timeline.data?.events?.length ? (
              <ol className="space-y-4">
                {timeline.data.events.slice(0, 16).map((e, i) => (
                  <li key={e.id || i} className="flex gap-3">
                    <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-teal-600" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-slate-800">
                          {human(e.kind || e.type)}
                        </p>
                        <Chip>{human(e.provenance || e.source)}</Chip>
                      </div>
                      <p className="mt-1 break-words text-sm leading-relaxed text-slate-600">
                        {e.message ||
                          e.note ||
                          (typeof e.value === "object"
                            ? JSON.stringify(e.value)
                            : String(e.value ?? ""))}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Observed{" "}
                        {timestamp(
                          e.observed_at || e.timestamp,
                          mode === "replay" &&
                            e.provenance !== "clinician" &&
                            e.type !== "review_action"
                            ? "recorded"
                            : "Asia/Kolkata",
                        )}
                        {e.available_at &&
                          " · Available " +
                            timestamp(
                              e.available_at,
                              mode === "replay" ? "recorded" : "Asia/Kolkata",
                            )}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <Empty title="No saved timeline events">
                Issued forecasts and recorded decisions appear at their evidence
                cutoff.
              </Empty>
            )}
          </Section>
          <Section
            title="Issued forecast receipts"
            kicker="Preserved original values"
          >
            {receiptList.data?.items?.length ? (
              <div className="space-y-2">
                {receiptList.data.items.slice(0, 8).map((r) => (
                  <Link
                    key={r.id}
                    className="flex min-h-14 flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 p-3 text-sm hover:bg-teal-50"
                    to={
                      "/patients/" +
                      patientId +
                      "?mode=" +
                      mode +
                      "&cursor=" +
                      cursor +
                      "&receipt=" +
                      r.id
                    }
                  >
                    <span className="font-medium text-slate-700">
                      <LockKeyhole size={14} className="mr-2 inline" />
                      {String(r.id).slice(0, 12)}
                    </span>
                    <span className="text-xs text-slate-500">
                      {timestamp(
                        r.issued_at,
                        r.clock_kind === "server_received"
                          ? "Asia/Kolkata"
                          : "recorded",
                      )}
                    </span>
                    <ChevronRight size={16} />
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">
                {mode === "feed"
                  ? "No arrival receipt has been issued. Compatible connected research readings are required."
                  : "No persistent receipts yet. Recorded playback is read-only until you freeze a forecast."}
              </p>
            )}
          </Section>
        </div>
        <div className="min-w-0 space-y-4">
          <div
            className={
              "rounded-2xl border p-5 " +
              (flagged
                ? "border-amber-200 bg-amber-50"
                : "border-teal-200 bg-teal-50/50")
            }
          >
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <Activity size={15} />
              Forecast signal
            </p>
            <h2 className="mt-3 text-xl font-semibold tracking-tight text-slate-900">
              {bad
                ? "Waiting for eligible data"
                : risk?.ongoing_high
                  ? "Observed high glucose"
                  : flagged
                    ? mode === "feed"
                      ? "Experimental excursion signal"
                      : "Upcoming excursion flagged"
                    : "No upcoming flag"}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">
              {bad
                ? "Unsupported predictions are withheld. Review data continuity before interpreting an absence of warnings."
                : risk?.ongoing_high
                  ? "The latest glucose is already above the research threshold. This is an observed state, separate from an upcoming event."
                  : flagged
                    ? mode === "feed"
                      ? "An experimental arrival-mode estimate crossed the retrospective operating point. Arrival-mode probability reliability remains unvalidated; review the receipt and remaining lead time."
                      : "The dedicated 30-minute classifier crossed its calibrated operating point. Review the evidence and document the next step."
                    : "The operating point has not been crossed. This does not establish clinical safety."}
            </p>
            <p className="mt-4 border-t border-slate-200/70 pt-3 text-xs leading-relaxed text-slate-500">
              Research workflow · no treatment or emergency-response guidance
            </p>
          </div>
          <CareAction item={review} user={user} />
          {patientId.startsWith("SIM-") &&
            ["admin", "clinician", "reviewer"].includes(user.role) && (
              <>
                <PublishTask patientId={patientId} />
                <ShareApprovedNote patientId={patientId} />
              </>
            )}
        </div>
      </div>
    </div>
  );
}

export function ReceiptCard({
  receipt,
  visibleAt,
}: {
  receipt: Receipt;
  visibleAt?: string;
}) {
  const visibleOutcomes = (receipt.outcomes || []).filter(
    (o) =>
      !visibleAt ||
      new Date(
        /Z$|[+-]\d\d:\d\d$/.test(o.available_at || o.target_time)
          ? o.available_at || o.target_time
          : (o.available_at || o.target_time) + "Z",
      ).getTime() <=
        new Date(
          /Z$|[+-]\d\d:\d\d$/.test(visibleAt) ? visibleAt : visibleAt + "Z",
        ).getTime(),
  );
  const primary = activeModel(receipt.snapshot);
  const zone =
    receipt.clock_kind === "server_received" ? "Asia/Kolkata" : "recorded";
  return (
    <Section
      title="Frozen forecast receipt"
      kicker="Original evidence, append-only outcome"
      actions={
        <Chip tone="violet">
          <LockKeyhole size={12} />
          Immutable issuance
        </Chip>
      }
    >
      <dl className="grid gap-4 sm:grid-cols-2">
        {[
          ["Issued", timestamp(receipt.issued_at, zone)],
          [
            "Input cutoff",
            timestamp(receipt.input_cutoff || receipt.issued_at, zone),
          ],
          [
            "Model version",
            receipt.model_version ||
              primary?.model?.version ||
              "Recorded in snapshot",
          ],
          ["Clock policy", human(receipt.clock_kind || "recorded")],
          [
            "Source connection",
            receipt.source_connection_id || "Public recorded dataset",
          ],
          [
            "Input digest",
            receipt.input_digest
              ? receipt.input_digest.slice(0, 18) + "…"
              : "Preserved snapshot",
          ],
        ].map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs text-slate-500">{k}</dt>
            <dd className="mt-1 break-all text-sm font-medium text-slate-800">
              {v}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-5 border-t border-slate-100 pt-4">
        {visibleOutcomes.length ? (
          <div className="space-y-3">
            {visibleOutcomes.map((o) => {
              const f = primary?.forecasts.twin?.find(
                (f) => f.horizon_minutes === o.horizon_minutes,
              );
              return (
                <div
                  key={o.horizon_minutes}
                  className="rounded-xl bg-teal-50 p-4"
                >
                  <p className="text-sm font-semibold text-teal-900">
                    Observed outcome · {o.horizon_minutes} minutes
                  </p>
                  <p className="mt-2 text-sm text-teal-800">
                    Issued {number(f?.glucose_mg_dl)} → observed{" "}
                    {number(o.actual_glucose_mg_dl)} mg/dL · absolute error{" "}
                    {f
                      ? number(
                          Math.abs(f.glucose_mg_dl - o.actual_glucose_mg_dl),
                        )
                      : "—"}{" "}
                    mg/dL
                  </p>
                  <p className="mt-2 text-xs text-teal-700">
                    Target {timestamp(o.target_time, zone)} · available{" "}
                    {timestamp(o.available_at, zone)}
                  </p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <Clock3 size={16} />
            Outcome pending. Nothing beyond the available time boundary is
            revealed.
          </p>
        )}
      </div>
    </Section>
  );
}

export function PatientDirectory() {
  const patients = usePatients();
  const [search, setSearch] = useState("");
  const shown = useMemo(
    () =>
      (patients.data || []).filter((p) =>
        (p.display_name + " " + p.id)
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
    [patients.data, search],
  );
  return (
    <div className="space-y-5">
      <Heading
        overline="Patient directory"
        title="Find the evidence behind a patient."
      />
      <Field label="Search patients">
        <input
          className={input + " max-w-md"}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Patient name or anonymized ID"
        />
      </Field>
      <ErrorBox error={patients.error} />
      {patients.isPending ? (
        <Loading />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((p) => (
            <Link
              key={p.id}
              className={surface + " group p-5 hover:border-teal-300"}
              to={"/patients/" + p.id}
            >
              <div className="flex items-center justify-between">
                <div className="rounded-xl bg-slate-50 p-3 text-teal-700">
                  <Fingerprint size={22} />
                </div>
                <ChevronRight
                  size={18}
                  className="text-slate-400 group-hover:text-teal-700"
                />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-800">
                {p.display_name || "Patient " + p.id}
              </h2>
              <p className="mt-1 text-sm text-slate-500">{p.id}</p>
              <div className="mt-4">
                <Chip tone={p.id.startsWith("SIM-") ? "violet" : "neutral"}>
                  {p.id.startsWith("SIM-")
                    ? "Fully synthetic"
                    : p.id.startsWith("PUB-")
                      ? "Public import"
                      : "Anonymized public CGM"}
                </Chip>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
