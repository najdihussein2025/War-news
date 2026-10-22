import { levelDisabledReason } from "../airRules";
import type { AnalyticsFilters, MetaResponse, Metric } from "../types";
import { metricLabel } from "./FilterBar";
import type { ReactNode } from "react";

export const FullMapToolbar = ({ filters, meta, onChange, play }: {
  filters: AnalyticsFilters; meta?: MetaResponse;
  onChange: (patch: Partial<AnalyticsFilters>) => void; play: ReactNode;
}) => {
  const select = "h-8 max-w-44 rounded-md border border-input-border bg-input-bg px-2 text-small focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring";
  return <div className="flex flex-wrap items-center justify-center gap-2" aria-label="Full map filters">
    <label className="sr-only" htmlFor="full-map-level">Map level</label>
    <select id="full-map-level" className={select} value={filters.level} onChange={(e) => onChange({ level: e.target.value as AnalyticsFilters["level"] })}>
      {(["mohafaza", "caza", "village"] as const).map((level) => <option key={level} value={level}
        disabled={!!levelDisabledReason(level, filters.airType, filters.metric === "breaches")}>{level === "mohafaza" ? "Mohafaza" : level === "caza" ? "Caza" : "Village"}</option>)}
    </select>
    <label className="sr-only" htmlFor="full-map-family">Action family</label>
    <select id="full-map-family" className={select} value={filters.families.length === 1 ? filters.families[0] : ""}
      disabled={filters.metric === "breaches"} onChange={(e) => onChange({ families: e.target.value ? [e.target.value] : [] })}>
      <option value="">{filters.families.length > 1 ? `${filters.families.length} selected families` : "All action families"}</option>
      {(meta?.families ?? []).map((family) => <option key={family.code} value={family.code}>{family.name_en}</option>)}
    </select>
    <label className="sr-only" htmlFor="full-map-metric">Metric</label>
    <select id="full-map-metric" className={select} value={filters.metric} onChange={(e) => onChange({ metric: e.target.value as Metric })}>
      {(["incidents", "deaths", "injuries", "casualties", "breaches"] as Metric[]).map((metric) => <option key={metric} value={metric}>{metricLabel(metric)}</option>)}
    </select>
    <span className="px-1 text-caption tabular-nums text-text-muted">{filters.dateFrom} – {filters.dateTo}</span>
    {play}
  </div>;
};
