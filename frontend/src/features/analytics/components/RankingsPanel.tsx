import { useState } from "react";
import { DataTable, type DataTableColumn } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { formatDate } from "../../../lib/formatters";
import { cn } from "../../../lib/cn";
import { familyColor } from "../colors";
import { toApiParams } from "../filters";
import { useRankings } from "../hooks";
import { formatNumber } from "../mappers";
import type { AnalyticsFilters, Level, Metric, RankingRow } from "../types";
import { FamilyDot, NameCell, errorMessage } from "./common";

type Tab = { id: string; label: string; level: Level; metric: Metric };
const TABS: Tab[] = [
  { id: "villages", label: "Most hit villages", level: "village", metric: "incidents" },
  { id: "deaths", label: "Most deaths", level: "village", metric: "deaths" },
  { id: "injuries", label: "Most injuries", level: "village", metric: "injuries" },
  { id: "caza", label: "By caza", level: "caza", metric: "incidents" },
  { id: "mohafaza", label: "By mohafaza", level: "mohafaza", metric: "incidents" },
];

type Props = {
  filters: AnalyticsFilters;
  familyNames: Record<string, string>;
  enabled: boolean;
  onFocusArea: (code: string, level: Level) => void;
};

export const RankingsPanel = ({ filters, familyNames, enabled, onFocusArea }: Props) => {
  const [tabId, setTabId] = useState("villages");
  const tab = TABS.find((t) => t.id === tabId) ?? TABS[0];
  // Rankings rank incident metrics; an area filter is dropped so the table can list the surrounding areas too.
  const metric = filters.metric === "breaches" && tab.metric === "incidents" ? "breaches" : tab.metric;
  const params = toApiParams(filters, { level: tab.level, metric, areaCode: null });
  const query = useRankings(params, tab.level === "village" ? 20 : 30, enabled);

  const valueHeader = metric === "breaches" ? "Breaches" : tab.metric === "incidents" ? "Incidents" : tab.metric === "deaths" ? "Deaths" : "Injuries";
  const columns: Array<DataTableColumn<RankingRow>> = [
    { key: "rank", header: "#", render: (_r, i) => <span className="tabular-nums text-text-muted">{i + 1}</span>, cellClassName: "w-10" },
    { key: "name", header: "Area", render: (r) => <NameCell en={r.name_en} ar={r.name_ar} sub={r.parent_name_en} />, sortValue: (r) => r.name_en ?? "" },
    { key: "value", header: valueHeader, render: (r) => <span className="font-semibold tabular-nums">{formatNumber(r.value)}</span>, sortValue: (r) => r.value, cellClassName: "text-right", headerClassName: "text-right" },
    ...(metric !== "breaches" ? [
      { key: "deaths", header: "Deaths", render: (r: RankingRow) => <span className="tabular-nums">{formatNumber(r.deaths)}</span>, sortValue: (r: RankingRow) => r.deaths ?? 0, cellClassName: "text-right", headerClassName: "text-right" },
      { key: "injuries", header: "Injuries", render: (r: RankingRow) => <span className="tabular-nums">{formatNumber(r.injuries)}</span>, sortValue: (r: RankingRow) => r.injuries ?? 0, cellClassName: "text-right", headerClassName: "text-right" },
    ] : []),
    { key: "dates", header: "First – last", render: (r) => <span className="whitespace-nowrap text-caption tabular-nums">{r.first_date ? formatDate(r.first_date) : "–"} – {r.last_date ? formatDate(r.last_date) : "–"}</span>, sortValue: (r) => r.last_date ?? "" },
    { key: "dominant", header: metric === "breaches" ? "Main type" : "Main action", render: (r) => r.dominant_family
      ? <span className="flex items-center gap-1.5 text-caption"><FamilyDot color={familyColor(r.dominant_family)} />{familyNames[r.dominant_family] ?? r.dominant_family}</span>
      : <span className="text-caption">{r.dominant_condition_label ?? "–"}</span> },
  ];

  return (
    <div>
      <div role="tablist" aria-label="Ranking views" className="mb-3 flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button key={t.id} role="tab" type="button" aria-selected={t.id === tabId} onClick={() => setTabId(t.id)}
            className={cn("h-9 rounded-md border px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
              t.id === tabId ? "border-brand-navy bg-brand-navy text-text-inverse" : "border-border hover:bg-surface-muted")}>{t.label}</button>
        ))}
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.rows ?? []}
        getRowKey={(r) => r.code}
        loading={query.isLoading}
        error={Boolean(query.error) && !query.data}
        errorState={<EmptyState title="Could not load rankings" description={errorMessage(query.error)} />}
        emptyState={<EmptyState title="No areas to rank" description="Nothing recorded for these filters." className="min-h-32" />}
        onRowClick={(r) => onFocusArea(r.code, r.level)}
        density="compact"
        minWidth="640px"
      />
      <p className="mt-2 text-caption text-text-muted">Click a row to focus the map and open the area profile.</p>
    </div>
  );
};
