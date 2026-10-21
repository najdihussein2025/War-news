import { useMemo, useState } from "react";
import { Select } from "../../../components/ui/Select";
import { cn } from "../../../lib/cn";
import { AIR_TYPES, levelDisabledReason } from "../airRules";
import { familyColor } from "../colors";
import { LEVELS } from "../filters";
import { formatNumber } from "../mappers";
import type { AnalyticsFilters, Family, Level, MetaResponse, Metric } from "../types";

const METRIC_LABELS: Record<Metric, string> = {
  incidents: "Incidents", deaths: "Deaths", injuries: "Injuries", casualties: "Deaths + injuries", breaches: "Air breaches",
};
export const metricLabel = (m: Metric): string => METRIC_LABELS[m];

type Props = {
  filters: AnalyticsFilters;
  meta: MetaResponse | undefined;
  today: string;
  onChange: (patch: Partial<AnalyticsFilters>) => void;
  onReset: () => void;
  resolveRange: (range: string) => { from: string; to: string };
  /** Period-scoped value from the KPI query; never use the all-time metadata count here. */
  pendingReview?: number;
};

const monthOptions = (meta: MetaResponse | undefined, today: string) => {
  const first = meta?.incident_data.first_date ?? today;
  const options: Array<{ label: string; value: string }> = [];
  let [y, m] = first.split("-").map(Number);
  const [ty, tm] = today.split("-").map(Number);
  while (y < ty || (y === ty && m <= tm)) {
    const label = new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
    options.push({ label, value: `m:${y}-${String(m).padStart(2, "0")}` });
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return options.reverse();
};

export const FilterBar = ({ filters, meta, today, onChange, onReset, resolveRange, pendingReview }: Props) => {
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
    <div className="sticky top-0 z-20 -mx-1 border-b border-border bg-surface-raised/95 px-1 py-3 backdrop-blur" role="search" aria-label="Analytics filters">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <fieldset className="min-w-0">
          <legend className="mb-1 text-caption font-semibold text-text-muted">Period</legend>
          <div className="flex flex-wrap items-center gap-1.5">
            {presets.map(([id, label]) => (
              <button key={id} type="button" aria-pressed={filters.range === id} onClick={() => setRange(id)}
                className={cn("h-9 rounded-md border px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
                  filters.range === id ? "border-brand-navy bg-brand-navy text-text-inverse" : "border-border bg-surface-raised hover:bg-surface-muted")}>{label}</button>
            ))}
            <Select id="war-month" value={isMonth ? filters.range : ""} placeholder="War month" options={months}
              onChange={(value) => value && setRange(value)} className={cn("w-40", isMonth && "ring-1 ring-brand-navy")} />
            <input type="date" aria-label="From date" value={filters.dateFrom} max={filters.dateTo}
              onChange={(e) => e.target.value && onChange({ range: "custom", dateFrom: e.target.value })}
              className="h-9 rounded-md border border-input-border bg-input-bg px-2 text-small tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring" />
            <span aria-hidden="true" className="text-text-muted">→</span>
            <input type="date" aria-label="To date" value={filters.dateTo} min={filters.dateFrom} max={today}
              onChange={(e) => e.target.value && onChange({ range: "custom", dateTo: e.target.value })}
              className="h-9 rounded-md border border-input-border bg-input-bg px-2 text-small tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring" />
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-1 text-caption font-semibold text-text-muted">Map level</legend>
          <div className="flex overflow-hidden rounded-md border border-border" role="group">
            {LEVELS.map((level: Level) => {
              const reason = levelDisabledReason(level, filters.airType, breaches);
              return (
                <button key={level} type="button" aria-pressed={filters.level === level} aria-disabled={Boolean(reason)} title={reason ?? undefined}
                  onClick={() => !reason && onChange({ level })}
                  className={cn("h-9 px-3 text-small font-medium capitalize focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring",
                    filters.level === level ? "bg-brand-navy text-text-inverse" : "bg-surface-raised hover:bg-surface-muted",
                    reason && "cursor-not-allowed text-text-muted opacity-50 hover:bg-surface-raised")}>{level}</button>
              );
            })}
          </div>
        </fieldset>

        <div className="relative">
          <span id="families-label" className="mb-1 block text-caption font-semibold text-text-muted">Action family</span>
          <button type="button" aria-haspopup="true" aria-expanded={familiesOpen} aria-labelledby="families-label" onClick={() => setFamiliesOpen((o) => !o)}
            className="flex h-9 min-w-44 items-center justify-between gap-2 rounded-md border border-input-border bg-input-bg px-3 text-small hover:border-input-border-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
            {filters.families.length === 0 ? "All families" : `${filters.families.length} selected`}
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

        <div>
          <label htmlFor="metric-select" className="mb-1 block text-caption font-semibold text-text-muted">Metric</label>
          <Select id="metric-select" value={filters.metric} placeholder="Metric" className="w-44"
            options={(Object.keys(METRIC_LABELS) as Metric[]).map((m) => ({ value: m, label: METRIC_LABELS[m] }))}
            onChange={(value) => onChange({ metric: value as Metric })} />
        </div>

        {breaches ? (
          <div>
            <label htmlFor="air-type" className="mb-1 block text-caption font-semibold text-text-muted">Air type</label>
            <Select id="air-type" value={filters.airType ? String(filters.airType) : ""} placeholder="All types" className="w-44"
              options={[{ value: "", label: "All types" }, ...AIR_TYPES.map((t) => ({ value: String(t.id), label: t.label }))]}
              onChange={(value) => onChange({ airType: value ? Number(value) : null })} />
          </div>
        ) : null}

        <label className="flex h-9 cursor-pointer items-center gap-2 text-small">
          <input type="checkbox" role="switch" checked={filters.includePending} onChange={(e) => onChange({ includePending: e.target.checked })} className="h-4 w-4" />
          Include pending review
          <span className="rounded-full bg-brand-gold-soft px-2 py-0.5 text-caption font-semibold tabular-nums text-yellow-600">{formatNumber(pendingReview ?? 0)}</span>
        </label>

        <button type="button" onClick={onReset} className="h-9 rounded-md border border-border px-3 text-small font-medium hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Reset</button>
        {filters.areaCode ? (
          <button type="button" onClick={() => onChange({ areaCode: null })} className="h-9 rounded-md border border-brand-gold bg-brand-gold-soft px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
            Area filter: {filters.areaCode} ✕
          </button>
        ) : null}
      </div>
    </div>
  );
};
