import { useMemo, useState } from "react";
import { Select } from "../../../components/ui/Select";
import { formatDate } from "../../../lib/formatters";
import { cn } from "../../../lib/cn";
import { AIR_TYPES, airTypeLabel, levelDisabledReason } from "../airRules";
import { familyColor } from "../colors";
import { LEVELS } from "../filters";
import { formatNumber } from "../mappers";
import type { AnalyticsFilters, Family, Level, MetaResponse, Metric } from "../types";

const METRIC_LABELS: Record<Metric, string> = {
  incidents: "Incidents", deaths: "Deaths", injuries: "Injuries", casualties: "Deaths + injuries", breaches: "Air breaches",
};
export const metricLabel = (m: Metric): string => METRIC_LABELS[m];

const focusRing = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring";
const segment = (active: boolean) => cn(
  "h-8 px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring",
  active ? "bg-brand-navy text-text-inverse" : "bg-surface-raised hover:bg-surface-muted",
);
const Divider = () => <span className="hidden h-6 w-px bg-border xl:block" aria-hidden="true" />;

type Props = {
  filters: AnalyticsFilters;
  meta: MetaResponse | undefined;
  today: string;
  onChange: (patch: Partial<AnalyticsFilters>) => void;
  resolveRange: (range: string) => { from: string; to: string };
  /** Period-scoped value from the KPI query; never use the all-time metadata count here. */
  pendingReview?: number;
};

const monthLabel = (value: string) => {
  const [y, m] = value.slice(2).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
};

const monthOptions = (meta: MetaResponse | undefined, today: string) => {
  const first = meta?.incident_data.first_date ?? today;
  const options: Array<{ label: string; value: string }> = [];
  let [y, m] = first.split("-").map(Number);
  const [ty, tm] = today.split("-").map(Number);
  while (y < ty || (y === ty && m <= tm)) {
    const value = `m:${y}-${String(m).padStart(2, "0")}`;
    options.push({ label: monthLabel(value), value });
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return options.reverse();
};

/** One compact row on wide screens; wraps on narrower ones. Visible labels live in the chips below. */
export const FilterBar = ({ filters, meta, today, onChange, resolveRange, pendingReview }: Props) => {
  const [familiesOpen, setFamiliesOpen] = useState(false);
  const families: Family[] = meta?.families ?? [];
  const months = useMemo(() => monthOptions(meta, today), [meta, today]);
  const breaches = filters.metric === "breaches";
  const presets: Array<[string, string]> = [["7d", "7 days"], ["30d", "30 days"], ["all", "All"]];
  const isMonth = filters.range.startsWith("m:");

  const setRange = (range: string) => {
    const { from, to } = resolveRange(range);
    onChange({ range, dateFrom: from, dateTo: to });
  };

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 py-2" role="search" aria-label="Analytics filters">
      <fieldset className="flex min-w-0 flex-wrap items-center gap-1.5">
        <legend className="sr-only">Period</legend>
        <div className="flex overflow-hidden rounded-md border border-border" role="group" aria-label="Period preset">
          {presets.map(([id, label], i) => (
            <button key={id} type="button" aria-pressed={filters.range === id} onClick={() => setRange(id)}
              className={cn(segment(filters.range === id), i > 0 && "border-l border-border")}>{label}</button>
          ))}
        </div>
        <Select id="war-month" size="sm" value={isMonth ? filters.range : ""} placeholder="War month" options={months}
          onChange={(value) => value && setRange(value)} className={cn("w-40", isMonth && "rounded-md ring-1 ring-brand-navy")} />
        <input type="date" aria-label="From date" value={filters.dateFrom} max={filters.dateTo}
          onChange={(e) => e.target.value && onChange({ range: "custom", dateFrom: e.target.value })}
          className={cn("h-8 w-[7.75rem] rounded-md border border-input-border bg-input-bg px-2 text-small tabular-nums", focusRing)} />
        <span aria-hidden="true" className="text-text-muted">→</span>
        <input type="date" aria-label="To date" value={filters.dateTo} min={filters.dateFrom} max={today}
          onChange={(e) => e.target.value && onChange({ range: "custom", dateTo: e.target.value })}
          className={cn("h-8 w-[7.75rem] rounded-md border border-input-border bg-input-bg px-2 text-small tabular-nums", focusRing)} />
      </fieldset>

      <Divider />

      <fieldset>
        <legend className="sr-only">Map level</legend>
        <div className="flex overflow-hidden rounded-md border border-border" role="group" aria-label="Map level">
          {LEVELS.map((level: Level, i) => {
            const reason = levelDisabledReason(level, filters.airType, breaches);
            return (
              <button key={level} type="button" aria-pressed={filters.level === level} aria-disabled={Boolean(reason)} title={reason ?? undefined}
                onClick={() => !reason && onChange({ level })}
                className={cn(segment(filters.level === level), "capitalize", i > 0 && "border-l border-border",
                  reason && "cursor-not-allowed text-text-muted opacity-50 hover:bg-surface-raised")}>{level}</button>
            );
          })}
        </div>
      </fieldset>

      <Divider />

      <div className="relative">
        <span id="families-label" className="sr-only">Action family</span>
        <button type="button" aria-haspopup="true" aria-expanded={familiesOpen} aria-labelledby="families-label families-value" onClick={() => setFamiliesOpen((o) => !o)}
          className={cn("flex h-8 items-center justify-between gap-2 rounded-md border border-input-border bg-input-bg px-3 text-small hover:border-input-border-hover", focusRing)}>
          <span id="families-value">{filters.families.length === 0 ? "All families" : `${filters.families.length} famil${filters.families.length === 1 ? "y" : "ies"}`}</span>
          <span aria-hidden="true">▾</span>
        </button>
        {familiesOpen ? (
          <div className="absolute left-0 top-full z-30 mt-1 w-72 rounded-md border border-border bg-surface-raised p-2 shadow-overlay" onKeyDown={(e) => e.key === "Escape" && setFamiliesOpen(false)}>
            <ul className="max-h-72 overflow-auto">
              {families.map((f) => {
                const checked = filters.families.includes(f.code);
                return (
                  <li key={f.code}>
                    <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-small hover:bg-surface-muted">
                      <input type="checkbox" checked={checked} className="h-4 w-4"
                        onChange={() => onChange({ families: checked ? filters.families.filter((c) => c !== f.code) : [...filters.families, f.code] })} />
                      <span className="inline-block h-3 w-3 rounded-sm" style={{ background: familyColor(f.code) }} aria-hidden="true" />
                      <span className="flex-1">{f.name_en}</span>
                      <span dir="rtl" lang="ar" className="text-caption text-text-muted">{f.name_ar}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
            <div className="mt-1 flex justify-between border-t border-border pt-2">
              <button type="button" className="text-small text-brand-navy underline" onClick={() => onChange({ families: [] })}>Clear</button>
              <button type="button" className="text-small font-semibold text-brand-navy" onClick={() => setFamiliesOpen(false)}>Done</button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-1.5">
        <label htmlFor="metric-select" className="sr-only">Metric</label>
        <Select id="metric-select" size="sm" value={filters.metric} placeholder="Metric" className="w-40"
          options={(Object.keys(METRIC_LABELS) as Metric[]).map((m) => ({ value: m, label: METRIC_LABELS[m] }))}
          onChange={(value) => onChange({ metric: value as Metric })} />
        {breaches ? (
          <>
            <label htmlFor="air-type" className="sr-only">Air type</label>
            <Select id="air-type" size="sm" value={filters.airType ? String(filters.airType) : ""} placeholder="All air types" className="w-48"
              options={[{ value: "", label: "All air types" }, ...AIR_TYPES.map((t) => ({ value: String(t.id), label: t.label }))]}
              onChange={(value) => onChange({ airType: value ? Number(value) : null })} />
          </>
        ) : null}
      </div>

      <Divider />

      <label className="flex h-8 cursor-pointer items-center gap-2 whitespace-nowrap text-small">
        <input type="checkbox" role="switch" checked={filters.includePending} onChange={(e) => onChange({ includePending: e.target.checked })} className="h-4 w-4" />
        Include pending
        <span className="rounded-full bg-brand-gold-soft px-2 py-0.5 text-caption font-semibold tabular-nums text-yellow-600">{formatNumber(pendingReview ?? 0)}</span>
      </label>
    </div>
  );
};

type Chip = { key: string; label: string; color?: string; remove: Partial<AnalyticsFilters> | "range" };

/** Every filter that differs from the default, each removable on its own. */
export const ActiveFilterChips = ({ filters, meta, areaName, onChange, onRemoveRange, onReset }: {
  filters: AnalyticsFilters;
  meta: MetaResponse | undefined;
  areaName: string | null;
  onChange: (patch: Partial<AnalyticsFilters>) => void;
  /** Back to the default period (30 days). */
  onRemoveRange: () => void;
  onReset: () => void;
}) => {
  const names = Object.fromEntries((meta?.families ?? []).map((f) => [f.code, f.name_en]));
  const chips: Chip[] = [];
  if (filters.range !== "30d") {
    const label = filters.range === "7d" ? "Last 7 days" : filters.range === "all" ? "All dates"
      : filters.range.startsWith("m:") ? monthLabel(filters.range) : `${formatDate(filters.dateFrom)} → ${formatDate(filters.dateTo)}`;
    chips.push({ key: "range", label, remove: "range" });
  }
  if (filters.areaCode) chips.push({ key: "area", label: `Area: ${areaName ?? filters.areaCode}`, remove: { areaCode: null } });
  if (filters.level !== "mohafaza") chips.push({ key: "level", label: `Level: ${filters.level}`, remove: { level: "mohafaza" } });
  if (filters.metric !== "incidents") chips.push({ key: "metric", label: `Metric: ${METRIC_LABELS[filters.metric]}`, remove: { metric: "incidents", airType: null } });
  if (filters.airType) chips.push({ key: "air", label: airTypeLabel(filters.airType), remove: { airType: null } });
  for (const code of filters.families) {
    chips.push({ key: `f-${code}`, label: names[code] ?? code, color: familyColor(code), remove: { families: filters.families.filter((c) => c !== code) } });
  }
  if (filters.includePending) chips.push({ key: "pending", label: "Including pending review", remove: { includePending: false } });
  if (chips.length === 0) return <p className="text-caption text-text-muted">Last 30 days · verified incidents · all action families</p>;

  return (
    <ul className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label="Active filters">
      {chips.map((chip) => (
        <li key={chip.key} className="flex h-7 items-center gap-1 rounded-full border border-border bg-surface-raised pl-2.5 pr-0.5 text-caption font-medium">
          {chip.color ? <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: chip.color }} aria-hidden="true" /> : null}
          <span className="max-w-[16rem] truncate" title={chip.label}>{chip.label}</span>
          <button type="button" aria-label={`Remove filter: ${chip.label}`}
            onClick={() => (chip.remove === "range" ? onRemoveRange() : onChange(chip.remove))}
            className={cn("flex h-6 w-6 items-center justify-center rounded-full text-text-muted hover:bg-surface-muted hover:text-text-primary", focusRing)}>
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
          </button>
        </li>
      ))}
      <li>
        <button type="button" onClick={onReset} className={cn("h-7 rounded-md px-2 text-caption font-semibold text-brand-navy underline-offset-2 hover:underline", focusRing)}>Reset all</button>
      </li>
    </ul>
  );
};
