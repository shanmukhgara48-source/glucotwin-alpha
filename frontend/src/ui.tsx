import type { ReactNode } from 'react';
import { CircleHelp } from 'lucide-react';
export const button = 'inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-40';
export const secondary = button + ' border border-[#dce5e3] bg-white text-[#33545a] hover:bg-[#eff5f3]';
export const primary = button + ' bg-[#153d3b] text-white hover:bg-[#20564e]';
export const card = 'rounded-2xl border border-[#e0e8e5] bg-white shadow-[0_3px_16px_-12px_rgba(19,56,60,0.2)]';
export const field = 'w-full rounded-lg border border-[#dce5e3] bg-white px-3 py-2.5 text-sm text-[#244d48] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100 disabled:bg-slate-50';
export const label = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
export const num = (value: unknown, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
export const percent = (value: unknown) => typeof value === 'number' ? num(value * 100, 1) + '%' : '—';
export function date(value?: string | null) { if (!value) return '—'; const zoned = value.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(value); const parsed = new Date(zoned ? value : value + 'Z'); return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + (zoned ? ' UTC' : ' · recorded time'); }
export function Badge({ children, amber = false }: { children: ReactNode; amber?: boolean }) { return <span className={'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ' + (amber ? 'bg-[#fff4dd] text-[#97611c]' : 'bg-[#e9f7f2] text-[#137565]')}>{children}</span>; }
export function Eyebrow({ children }: { children: ReactNode }) { return <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#5e706b]">{children}</div>; }
export function Empty({ children }: { children: ReactNode }) { return <div className="flex min-h-36 flex-col items-center justify-center gap-3 px-5 py-8 text-center text-xs leading-relaxed text-[#61736b]"><CircleHelp size={22} />{children}</div>; }
export function Title({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) { return <div><Eyebrow>{eyebrow}</Eyebrow><h1 className="mt-2 text-[27px] font-semibold tracking-[-0.04em] text-[#183e40]">{title}<span className="text-[#6a8d81]">.</span></h1><p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-[#5c6f63]">{children}</p></div>; }
