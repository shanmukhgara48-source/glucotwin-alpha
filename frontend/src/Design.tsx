import type { ReactNode } from "react";
import { useRef } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  LoaderCircle,
  Waves,
  X,
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";

export const surface =
  "rounded-2xl border border-slate-200/90 bg-white shadow-[0_8px_30px_-24px_rgba(16,38,56,0.35)]";
export const input =
  "min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus-visible:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600/20 disabled:bg-slate-100";
export const action =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-not-allowed disabled:opacity-50";
export const solid = action + " bg-teal-800 text-white hover:bg-teal-900";
export const outline =
  action + " border border-slate-200 bg-white text-slate-700 hover:bg-slate-50";
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-900 text-teal-100">
        <Waves size={25} />
      </div>
      {!compact && (
        <div>
          <div className="text-lg font-bold tracking-tight text-slate-900">
            GlucoTwin<span className="ml-1 text-teal-700">.</span>
          </div>
          <p className="mt-0.5 text-xs font-medium text-slate-500">
            Care, with evidence
          </p>
        </div>
      )}
    </div>
  );
}
export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "teal" | "amber" | "violet" | "red";
}) {
  const colors = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    teal: "border-teal-200 bg-teal-50 text-teal-800",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    violet: "border-violet-200 bg-violet-50 text-violet-800",
    red: "border-rose-200 bg-rose-50 text-rose-800",
  };
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold " +
        colors[tone]
      }
    >
      {children}
    </span>
  );
}
export function Heading({
  overline,
  title,
  children,
  actions,
}: {
  overline: string;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">
          {overline}
        </p>
        <h1 className="mt-2 text-[28px] font-semibold leading-tight tracking-[-0.045em] text-slate-900 sm:text-[32px]">
          {title}
        </h1>
        {children && (
          <div className="mt-2 max-w-2xl text-base leading-relaxed text-slate-500">
            {children}
          </div>
        )}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
export function Section({
  title,
  kicker,
  children,
  actions,
  className = "",
}: {
  title: string;
  kicker?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={surface + " " + className}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          {kicker && (
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
              {kicker}
            </p>
          )}
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
        </div>
        {actions}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}
export function Metric({
  label,
  value,
  note,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "neutral" | "teal" | "amber";
}) {
  return (
    <div
      className={
        surface +
        " p-5 " +
        (tone === "teal"
          ? "!border-teal-200 !bg-teal-50/50"
          : tone === "amber"
            ? "!border-amber-200 !bg-amber-50/50"
            : "")
      }
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
        {value}
      </div>
      {note && (
        <div className="mt-2 text-xs leading-relaxed text-slate-500">
          {note}
        </div>
      )}
    </div>
  );
}
export function Loading({ label = "Loading workspace…" }: { label?: string }) {
  return (
    <div
      role="status"
      className="flex min-h-40 items-center justify-center gap-3 text-sm text-slate-500"
    >
      <LoaderCircle
        size={20}
        className="animate-spin motion-reduce:animate-none"
      />
      {label}
    </div>
  );
}
export function Empty({
  title,
  children,
  action: cta,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center p-7 text-center">
      <div className="mb-4 rounded-2xl bg-slate-50 p-3 text-teal-700">
        <ArrowUpRight size={24} />
      </div>
      <h3 className="text-base font-semibold text-slate-800">{title}</h3>
      {children && (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500">
          {children}
        </p>
      )}
      {cta && <div className="mt-4">{cta}</div>}
    </div>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
    >
      <AlertCircle size={18} className="shrink-0" />
      <p className="min-w-0 flex-1">
        {error instanceof Error ? error.message : String(error)}
      </p>
      {retry && (
        <button className={outline} onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Modal({
  open,
  setOpen,
  title,
  description,
  children,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const restoreFocus = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-950/35 backdrop-blur-sm" />
        <Dialog.Content
          onOpenAutoFocus={() => {
            restoreFocus.current = document.activeElement as HTMLElement | null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocus.current?.focus();
          }}
          className="fixed left-1/2 top-1/2 z-50 max-h-[85dvh] w-[calc(100%_-_2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
        >
          <Dialog.Title className="pr-10 text-xl font-semibold tracking-tight text-slate-900">
            {title}
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm leading-relaxed text-slate-500">
            {description}
          </Dialog.Description>
          <Dialog.Close
            className={outline + " absolute right-3 top-3 !px-3"}
            aria-label="Close dialog"
          >
            <X size={18} />
          </Dialog.Close>
          <div className="mt-5">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-1.5 block text-xs leading-relaxed text-slate-500">
          {hint}
        </span>
      )}
    </label>
  );
}
export function timestamp(value?: string | null, zone = "Asia/Kolkata") {
  if (!value) return "Not recorded";
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + "Z");
  return Number.isNaN(d.getTime())
    ? value
    : new Intl.DateTimeFormat("en-IN", {
        timeZone: zone === "recorded" ? "UTC" : zone,
        dateStyle: "medium",
        timeStyle: "short",
      }).format(d) +
        " · " +
        (zone === "recorded" ? "dataset clock (zone unverified)" : zone);
}
export const number = (v: unknown, d = 1) =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—";
export const percentage = (v: unknown) =>
  typeof v === "number" ? Math.round(v * 100) + "%" : "—";
export const human = (v: unknown) =>
  String(v ?? "Not recorded")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
