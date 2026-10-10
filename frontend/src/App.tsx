import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  ChevronRight,
  ClipboardList,
  Database,
  FileUp,
  Fingerprint,
  FlaskConical,
  HeartHandshake,
  LogOut,
  Menu,
  ShieldCheck,
  Users,
  Waves,
  WifiOff,
  X,
} from "lucide-react";
import { api, post, setCsrf, setToken } from "./api";
import type { Benchmark, Provenance, User } from "./types";
import { InternalEvidence } from "./ClinicBenchmark";
import { BenchmarkView, ProvenanceView } from "./ResearchViews";
import {
  PatientDirectory,
  PatientWorkspace,
  ReviewDesk,
} from "./ClinicalWorkspace";
import {
  AccountSecurity,
  AdminView,
  IntakeDesk,
  OperationsView,
  PatientCompanion,
} from "./PlatformViews";
import {
  Chip,
  ErrorBox,
  Field,
  Heading,
  human,
  input,
  Loading,
  Logo,
  outline,
  solid,
  surface,
} from "./Design";
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15000, retry: 1, refetchOnWindowFocus: true },
  },
});
interface Session {
  user: User;
  csrf_token: string;
  expires_at?: string;
}
function Login({
  signedIn,
  expired,
}: {
  signedIn: (s: Session) => void;
  expired: boolean;
}) {
  const [username, setUsername] = useState("reviewer");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [activation, setActivation] = useState(false);
  const [invitation, setInvitation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (activation) {
        await post("/v2/auth/activate", {
          invitation_code: invitation,
          password,
        });
        setActivation(false);
        setPassword("");
        setInvitation("");
        setNotice(
          "Invitation activated. Sign in with the username supplied by your administrator.",
        );
      } else {
        const data = await post<Session>("/v2/auth/login", {
          username,
          password,
          ...(otp ? { otp } : {}),
        });
        setCsrf(data.csrf_token);
        signedIn(data);
      }
    } catch (c) {
      setError(c instanceof Error ? c.message : String(c));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid min-h-dvh bg-[#f4f6f8] lg:grid-cols-[1.05fr_0.95fr]">
      <div className="relative flex min-h-[340px] flex-col justify-between overflow-hidden bg-[#102d35] px-7 py-8 text-white sm:px-12 lg:px-16 lg:py-12">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/15 bg-white/10">
              <Waves size={26} />
            </div>
            <p className="text-xl font-semibold tracking-tight">
              GlucoTwin<span className="text-teal-300">.</span>
            </p>
          </div>
          <span className="rounded-full border border-white/15 px-3 py-1.5 text-xs text-teal-100">
            Research workspace
          </span>
        </div>
        <div className="relative my-12 max-w-xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-300">
            A model that learns. A record that remembers.
          </p>
          <h1 className="mt-5 text-[38px] font-medium leading-[1.08] tracking-[-0.05em] sm:text-[48px] lg:text-[56px]">
            Better care starts
            <br />
            with clearer evidence.
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-slate-300">
            Watch a patient model evolve, inspect what it knew, and turn a
            forecast into an accountable next step.
          </p>
          <div className="mt-9 rounded-2xl border border-white/15 bg-white/5 p-5">
            <div className="flex items-center justify-between text-xs text-slate-300">
              <span>THE GLUCOTWIN EVIDENCE LOOP</span>
              <Fingerprint size={16} />
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-2">
              {["Observe", "Forecast", "Review", "Learn"].map((v, i) => (
                <span key={v} className="flex items-center gap-2">
                  <span
                    className={
                      "rounded-lg px-3 py-2 text-sm " +
                      (i === 1
                        ? "bg-teal-300 text-teal-950"
                        : "bg-white/10 text-white")
                    }
                  >
                    {v}
                  </span>
                  {i < 3 && (
                    <ChevronRight size={14} className="text-teal-300" />
                  )}
                </span>
              ))}
            </div>
            <svg
              viewBox="0 0 450 100"
              role="img"
              aria-label="Decorative trajectory; no patient data"
              className="mt-5 h-20 w-full"
            >
              <path
                d="M0 72 L25 68 L55 72 L85 65 L105 52 L130 60 L158 39 L185 43 L218 24 L245 34 L265 29 L290 41 L315 31 L342 39"
                fill="none"
                stroke="#99e1d3"
                strokeWidth="2.5"
              />
              <path
                d="M342 39 L375 20 L410 28 L450 13"
                fill="none"
                stroke="#5eead4"
                strokeWidth="2.5"
                strokeDasharray="5 5"
              />
              <path
                d="M342 39 L375 8 L410 9 L450 0 L450 39 L410 46 L375 40 Z"
                fill="#5eead4"
                opacity=".1"
              />
              <line
                x1="342"
                y1="0"
                x2="342"
                y2="95"
                stroke="#94a3b8"
                strokeDasharray="3 4"
              />
            </svg>
          </div>
        </div>
        <p className="max-w-lg text-xs leading-relaxed text-slate-400">
          Public CGM playback and labeled synthetic collection. Clinical device
          access, clinician workflow review, and prospective validation remain
          pending.
        </p>
      </div>
      <main className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-[420px]">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">
            Authorized access
          </p>
          <h2 className="mt-3 text-[30px] font-semibold tracking-tight text-slate-900">
            {activation
              ? "Activate your invitation"
              : "Welcome to your workspace"}
          </h2>
          <p className="mt-3 text-base leading-relaxed text-slate-500">
            {activation
              ? "Use the private code from your clinic administrator."
              : "Sign in as a clinician, coordinator, administrator, or linked research patient."}
          </p>
          {expired && (
            <p
              role="status"
              className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
            >
              Your session ended. Sign in to continue. Unsaved care notes remain
              private to this browser tab.
            </p>
          )}
          {notice && (
            <p
              role="status"
              className="mt-5 rounded-xl bg-teal-50 p-4 text-sm text-teal-800"
            >
              {notice}
            </p>
          )}
          <form className="mt-7 space-y-5" onSubmit={(e) => void submit(e)}>
            {activation ? (
              <Field label="Private invitation code">
                <input
                  aria-label="Invitation code"
                  className={input}
                  value={invitation}
                  onChange={(e) => setInvitation(e.target.value)}
                  required
                  autoComplete="off"
                />
              </Field>
            ) : (
              <Field label="Username">
                <input
                  aria-label="Username"
                  className={input}
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </Field>
            )}
            <Field
              label={activation ? "Choose a password" : "Password"}
              hint={activation ? "Use at least 12 characters." : undefined}
            >
              <input
                aria-label="Password"
                className={input}
                type="password"
                autoComplete={activation ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={activation ? 12 : undefined}
              />
            </Field>
            {!activation && (
              <details>
                <summary className="min-h-11 cursor-pointer text-sm text-slate-500">
                  Using a two-factor code?
                </summary>
                <Field label="Authenticator code">
                  <input
                    aria-label="Authenticator code"
                    className={input}
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value)}
                  />
                </Field>
              </details>
            )}
            <ErrorBox error={error} />
            <button className={solid + " w-full"} disabled={busy}>
              {busy
                ? "Please wait…"
                : activation
                  ? "Activate account"
                  : "Sign in securely"}
              <ArrowRight size={17} />
            </button>
          </form>
          <button
            className="mt-4 min-h-11 text-sm font-medium text-teal-800 underline underline-offset-4"
            onClick={() => {
              setActivation(!activation);
              setError("");
              setNotice("");
            }}
          >
            {activation ? "Return to sign in" : "Activate a clinic invitation"}
          </button>
          <div className="mt-8 flex items-start gap-3 border-t border-slate-200 pt-5">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-teal-700" />
            <p className="text-xs leading-relaxed text-slate-500">
              Sessions use protected cookies. Credentials and activation codes
              stay out of public source and demonstration recordings.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
function EvidencePage() {
  const current = useQuery({
    queryKey: ["clinic-benchmark"],
    queryFn: () => api<Record<string, unknown>>("/clinic-benchmark"),
  });
  const legacy = useQuery({
    queryKey: ["benchmarks"],
    queryFn: () => api<Benchmark>("/benchmarks"),
  });
  return (
    <div className="space-y-6">
      <Heading
        overline="Model evidence"
        title="Make the result easy to challenge."
      >
        Measured retrospective evaluation, calibration, ablations, and
        unsuccessful forecasts.
      </Heading>
      <ErrorBox error={current.error || legacy.error} />
      {current.isPending ? (
        <Loading />
      ) : (
        <InternalEvidence evidence={current.data || null} />
      )}
      <details className={surface + " p-5"}>
        <summary className="min-h-11 cursor-pointer text-base font-semibold text-slate-700">
          Legacy reference benchmark
        </summary>
        <p className="mb-4 text-sm text-slate-500">
          A different earlier split; results are not a paired improvement
          comparison with the current five-fold model.
        </p>
        <BenchmarkView benchmark={legacy.data || null} />
      </details>
    </div>
  );
}
function LineagePage() {
  const p = useQuery({
    queryKey: ["provenance"],
    queryFn: () => api<Provenance>("/provenance"),
  });
  return (
    <div className="space-y-5">
      <ErrorBox error={p.error} />
      {p.isPending ? (
        <Loading />
      ) : (
        <ProvenanceView provenance={p.data || null} />
      )}
    </div>
  );
}
const nav = [
  { path: "/review", label: "Review desk", icon: ClipboardList },
  { path: "/patients", label: "Patient directory", icon: Users },
  { path: "/operations", label: "Operations", icon: Activity },
  { path: "/intake", label: "Data intake", icon: FileUp, admin: true },
  { path: "/evidence", label: "Model evidence", icon: BarChart3 },
  { path: "/lineage", label: "Data lineage", icon: Database },
  { path: "/admin", label: "Clinic settings", icon: ShieldCheck, admin: true },
];
function Workspace() {
  const client = useQueryClient();
  const location = useLocation();
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [expired, setExpired] = useState(false);
  const [menu, setMenu] = useState(false);
  const navigationRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!menu || window.matchMedia("(min-width: 1024px)").matches) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = navigationRef.current;
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          "a[href],button:not([disabled])",
        ) || [],
      ).filter((el) => el.getClientRects().length);
    focusable()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMenu(false);
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [menu]);
  const [online, setOnline] = useState(navigator.onLine);
  const [install, setInstall] = useState<
    (Event & { prompt: () => Promise<void> }) | null
  >(null);
  useEffect(() => {
    setToken(null);
    api<Session>("/v2/auth/me")
      .then((s) => {
        setSession(s);
        setCsrf(s.csrf_token);
      })
      .catch(() => undefined)
      .finally(() => setReady(true));
    const expiry = () => {
      setSession(null);
      setCsrf("");
      setExpired(true);
      client.clear();
    };
    const online = () => setOnline(navigator.onLine);
    const prompt = (e: Event) => {
      e.preventDefault();
      setInstall(e as Event & { prompt: () => Promise<void> });
    };
    window.addEventListener("glucotwin:session-expired", expiry);
    window.addEventListener("online", online);
    window.addEventListener("offline", online);
    window.addEventListener("beforeinstallprompt", prompt);
    return () => {
      window.removeEventListener("glucotwin:session-expired", expiry);
      window.removeEventListener("online", online);
      window.removeEventListener("offline", online);
      window.removeEventListener("beforeinstallprompt", prompt);
    };
  }, [client]);
  useEffect(() => {
    setMenu(false);
    document.title =
      "GlucoTwin · " +
      (session?.user.role === "patient"
        ? "Your companion"
        : nav.find((n) => location.pathname.startsWith(n.path))?.label ||
          "Patient workspace");
  }, [location.pathname, session?.user.role]);
  useEffect(() => {
    if (!session || session.user.role === "patient") return;
    const event = new EventSource("/api/v2/events", { withCredentials: true });
    const update = () => {
      for (const key of [
        "queue",
        "receipts",
        "receipt",
        "operations",
        "timeline",
        "patients",
      ])
        void client.invalidateQueries({ queryKey: [key] });
    };
    event.addEventListener("update", update);
    return () => event.close();
  }, [session, client]);
  async function logout() {
    try {
      await post("/v2/auth/logout", {});
    } finally {
      setCsrf("");
      setToken(null);
      setSession(null);
      setExpired(false);
      client.clear();
      for (const key of Object.keys(sessionStorage))
        if (key.startsWith("glucotwin.draft.")) sessionStorage.removeItem(key);
    }
  }
  if (!ready)
    return (
      <div className="flex min-h-dvh items-center justify-center bg-slate-50">
        <Loading label="Restoring protected session…" />
      </div>
    );
  if (!session)
    return (
      <Login
        expired={expired}
        signedIn={(s) => {
          setSession(s);
          setExpired(false);
          client.clear();
        }}
      />
    );
  const user = session.user;
  const isPatient = user.role === "patient";
  const links = isPatient
    ? [{ path: "/companion", label: "Your companion", icon: HeartHandshake }]
    : nav.filter((n) => !n.admin || user.role === "admin");
  const active = location.pathname.startsWith("/patients/")
    ? { label: "Patient twin workspace" }
    : links.find((n) => location.pathname.startsWith(n.path));
  return (
    <div className="min-h-dvh bg-[#f4f6f8] text-slate-700 lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <a
        className="fixed left-4 top-3 z-[80] -translate-y-20 rounded-xl bg-teal-900 px-5 py-3 text-white focus:translate-y-0"
        href="#main"
      >
        Skip to main content
      </a>
      <aside
        ref={navigationRef}
        className={
          "fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col border-r border-slate-200 bg-white p-4 shadow-xl transition-transform lg:sticky lg:top-0 lg:h-dvh lg:w-auto lg:translate-x-0 lg:shadow-none " +
          (menu ? "translate-x-0" : "hidden lg:flex")
        }
      >
        <div className="flex items-center justify-between px-1 py-3">
          <Logo />
          <button
            className={outline + " !px-3 lg:hidden"}
            onClick={() => setMenu(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>
        <p className="mt-8 px-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
          {isPatient ? "Personal workspace" : "Clinic workspace"}
        </p>
        <nav aria-label="Main navigation" className="mt-3 space-y-1.5">
          {links.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                "flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors " +
                (isActive
                  ? "bg-teal-50 text-teal-900"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-800")
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto pt-6">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-100 text-xs font-semibold text-teal-900">
                {(user.name || user.username)
                  .split(" ")
                  .slice(0, 2)
                  .map((s) => s[0])
                  .join("")
                  .toUpperCase()}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800">
                  {user.name || user.username}
                </p>
                <p className="text-xs text-slate-500">{human(user.role)}</p>
              </div>
            </div>
            <button
              className={outline + " mt-4 w-full"}
              onClick={() => void logout()}
            >
              <LogOut size={15} />
              Sign out
            </button>
          </div>
          {install && (
            <button
              className={outline + " mt-3 w-full"}
              onClick={() => void install.prompt().then(() => setInstall(null))}
            >
              Install workspace
            </button>
          )}
          {!isPatient && <AccountSecurity />}
          <p className="px-2 pt-4 text-xs leading-relaxed text-slate-400">
            Team alpha · Research prototype
            <br />
            Clinical release gates pending
          </p>
        </div>
      </aside>
      {menu && (
        <button
          className="fixed inset-0 z-30 bg-slate-950/25 lg:hidden"
          aria-label="Close navigation overlay"
          onClick={() => setMenu(false)}
        />
      )}
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex min-h-[72px] items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur sm:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <button
              className={outline + " !px-3 lg:hidden"}
              onClick={() => setMenu(true)}
              aria-label="Open navigation"
            >
              <Menu size={19} />
            </button>
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <span className="hidden text-slate-400 sm:inline">
                {isPatient ? "My record" : user.clinic_id}
              </span>
              <ChevronRight
                size={14}
                className="hidden text-slate-300 sm:block"
              />
              <span className="truncate font-medium text-slate-700">
                {active?.label || "Patient twin workspace"}
              </span>
            </div>
          </div>
          <Chip tone="violet">
            <FlaskConical size={12} />
            <span className="hidden sm:inline">Research environment · </span>
            Clinical gates pending
          </Chip>
        </header>
        {!online && (
          <div
            role="status"
            className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-900"
          >
            <WifiOff size={17} />
            Connection unavailable. New actions require the server; unsaved
            notes remain in this browser tab.
          </div>
        )}
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto min-w-0 max-w-[1600px] px-4 py-6 outline-none sm:px-7 sm:py-7"
        >
          <Routes>
            {isPatient ? (
              <>
                <Route path="/companion" element={<PatientCompanion />} />
                <Route
                  path="*"
                  element={<Navigate to="/companion" replace />}
                />
              </>
            ) : (
              <>
                <Route path="/review" element={<ReviewDesk user={user} />} />
                <Route path="/patients" element={<PatientDirectory />} />
                <Route
                  path="/patients/:patientId"
                  element={<PatientWorkspace user={user} />}
                />
                <Route
                  path="/operations"
                  element={<OperationsView user={user} />}
                />
                <Route path="/evidence" element={<EvidencePage />} />
                <Route path="/lineage" element={<LineagePage />} />
                {user.role === "admin" && (
                  <>
                    <Route
                      path="/intake"
                      element={<IntakeDesk user={user} />}
                    />
                    <Route path="/admin" element={<AdminView user={user} />} />
                  </>
                )}
                <Route path="*" element={<Navigate to="/review" replace />} />
              </>
            )}
          </Routes>
        </main>
      </div>
    </div>
  );
}
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Workspace />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
