import { useMemo, useState } from "react";
import { DataTable, type DataTableColumn } from "../../../../components/ui/DataTable";
import { formatDate } from "../../../../lib/formatters";
import { cn } from "../../../../lib/cn";
import { familyColor } from "../../colors";
import { formatNumber, sparkPath } from "../../mappers";
import type { Level, MapTab, NewlyTargetedVillage, RankedArea, RankingView } from "../../types";
import { ParetoChart, PARETO_CHART_LIMIT } from "../charts/MapCharts";
import { CsvButton, EmptyState, ErrorBlock, FamilyDot, NameCell, SectionCard, Skeleton, errorMessage } from "../common";

type Props = {
  data: MapTab | undefined;
  error: unknown;
  onRetry: () => void;
  familyNames: Record<string, string>;
  metricLabel: string;
  fileSuffix: string;
  onFocusArea: (code: string, level: Level) => void;
};

const VALUE_HEADER: Record<string, string> = {
  incidents: "Incidents", deaths: "Deaths", injuries: "Injuries", casualties: "Casualties", breaches: "Breaches",
};

const Trend = ({ values, weeks }: { values: number[]; weeks: string[] }) => (
  <svg viewBox="0 0 100 20" className="h-5 w-24" preserveAspectRatio="none" role="img"
    aria-label={`Weekly: ${values.join(", ")}`}>
    <path d={sparkPath(values.map((value, i) => ({ date: weeks[i] ?? String(i), value })), 100, 20)} fill="none" stroke="#082d6f" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
  </svg>
);

const rankingColumns = (view: RankingView, weeks: string[], familyNames: Record<string, string>): Array<DataTableColumn<RankedArea>> => [
  { key: "rank", header: "#", render: (r) => <span className="tabular-nums text-text-muted">{r.rank}</span>, sortValue: (r) => r.rank, cellClassName: "w-10" },
  { key: "area", header: "Area", render: (r) => <NameCell en={r.name_en} ar={r.name_ar} sub={r.parent_name_en} />, sortValue: (r) => r.name_en ?? "" },
  { key: "value", header: VALUE_HEADER[view.metric] ?? "Value", render: (r) => <span className="font-semibold tabular-nums">{formatNumber(r.value)}</span>, sortValue: (r) => r.value, cellClassName: "text-right", headerClassName: "text-right" },
  { key: "share", header: "Share", render: (r) => <span className="tabular-nums">{r.share_pct === null ? "–" : `${r.share_pct}%`}</span>, sortValue: (r) => r.share_pct ?? 0, cellClassName: "text-right", headerClassName: "text-right" },
  { key: "days", header: "Days hit", render: (r) => <span className="tabular-nums">{formatNumber(r.days_hit)}</span>, sortValue: (r) => r.days_hit, cellClassName: "text-right", headerClassName: "text-right" },
  { key: "last7", header: "Last 7 days", render: (r) => <span className="tabular-nums">{formatNumber(r.last_7d)}</span>, sortValue: (r) => r.last_7d, cellClassName: "text-right", headerClassName: "text-right" },
  { key: "trend", header: "Weekly trend", render: (r) => <Trend values={r.trend} weeks={weeks} /> },
  { key: "dates", header: "First – last", render: (r) => <span className="whitespace-nowrap text-caption tabular-nums">{r.first_date ? formatDate(r.first_date) : "–"} – {r.last_date ? formatDate(r.last_date) : "–"}</span>, sortValue: (r) => r.last_date ?? "" },
  { key: "main", header: "Main action", render: (r) => r.dominant_family
    ? <span className="flex items-center gap-1.5 text-caption"><FamilyDot color={familyColor(r.dominant_family)} />{familyNames[r.dominant_family] ?? r.dominant_family}</span>
    : <span className="text-caption">{r.dominant_condition_label ?? "–"}</span> },
];

const NEW_COLUMNS: Array<DataTableColumn<NewlyTargetedVillage>> = [
  { key: "village", header: "Village", render: (r) => <NameCell en={r.name_en} ar={r.name_ar} />, sortValue: (r) => r.name_en },
  { key: "caza", header: "Caza", render: (r) => <NameCell en={r.caza_en} ar={r.caza_ar} />, sortValue: (r) => r.caza_en ?? "" },
  { key: "first", header: "First incident", render: (r) => <span className="whitespace-nowrap tabular-nums">{formatDate(r.first_date)}</span>, sortValue: (r) => r.first_date },
  { key: "since", header: "Since then", render: (r) => <span className="font-semibold tabular-nums">{formatNumber(r.incidents_since)}</span>, sortValue: (r) => r.incidents_since, cellClassName: "text-right", headerClassName: "text-right" },
];

/** Everything on the Map tab below the map: rankings, newly targeted villages, concentration (Pareto). */
export const MapSections = ({ data, error, onRetry, familyNames, metricLabel, fileSuffix, onFocusArea }: Props) => {
  const views = data?.rankings.views ?? [];
  const [viewId, setViewId] = useState("villages");
  const view = views.find((v) => v.id === viewId) ?? views[0];
  const weeks = data?.rankings.weeks ?? [];
  const columns = useMemo(() => (view ? rankingColumns(view, weeks, familyNames) : []), [view, weeks, familyNames]);
  const failed = error && !data ? <ErrorBlock message={errorMessage(error)} onRetry={onRetry} /> : null;
  const pareto = data?.pareto;
  const newly = data?.newly_targeted;

  return (
    <>
      <div className="col-span-12">
        <SectionCard id="map-rankings" title="Rankings" subtitle={view ? `${VALUE_HEADER[view.metric] ?? metricLabel} by ${view.level}: share of the total ${formatNumber(view.total)}, days with an incident, the last 7 days of the period and the weekly trend` : "Areas ranked by the selected metric"}
          actions={<CsvButton filename={`rankings_${view?.id ?? "areas"}_${fileSuffix}`} disabled={!view}
            headers={["rank", "area", "area (ar)", "parent", "value", "share %", "days hit", "last 7 days", "first date", "last date", "main action", ...weeks.map((w) => `week of ${w}`)]}
            rows={() => (view?.rows ?? []).map((r) => [r.rank, r.name_en, r.name_ar, r.parent_name_en, r.value, r.share_pct, r.days_hit, r.last_7d, r.first_date, r.last_date,
              r.dominant_family ? familyNames[r.dominant_family] ?? r.dominant_family : r.dominant_condition_label ?? "", ...r.trend])} />}>
          {failed ?? (!data ? <Skeleton className="h-[38rem]" /> : (
            <>
              <div role="tablist" aria-label="Ranking views" className="mb-3 flex flex-wrap gap-1.5">
                {views.map((v) => (
                  <button key={v.id} role="tab" type="button" aria-selected={v.id === view?.id} onClick={() => setViewId(v.id)}
                    className={cn("h-8 rounded-md border px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
                      v.id === view?.id ? "border-brand-navy bg-brand-navy text-text-inverse" : "border-border hover:bg-surface-muted")}>{v.label}</button>
                ))}
              </div>
              {view ? (
                <DataTable key={view.id} columns={columns} rows={view.rows} getRowKey={(r) => r.code} pageSize={25} density="compact" minWidth="1040px"
                  initialSort={{ key: "rank", direction: "asc" }} onRowClick={(r) => onFocusArea(r.code, r.level)}
                  emptyState={<EmptyState>Nothing recorded for these filters.</EmptyState>} />
              ) : null}
              <p className="mt-1.5 text-caption text-text-muted">Up to 100 areas per view. Select a row to focus the map on that area.</p>
            </>
          ))}
        </SectionCard>
      </div>

      <div className="col-span-12 xl:col-span-5">
        <SectionCard id="newly-targeted" className="h-full" title="Newly targeted villages" subtitle={newly?.note ?? "Villages whose first recorded incident falls in this period"}
          actions={<CsvButton filename={`newly_targeted_${fileSuffix}`} disabled={!newly}
            headers={["village", "village (ar)", "caza", "first incident", "incidents since"]}
            rows={() => (newly?.rows ?? []).map((r) => [r.name_en, r.name_ar, r.caza_en, r.first_date, r.incidents_since])} />}>
          {failed ?? (!newly ? <Skeleton className="h-[26rem]" /> : (
            <DataTable columns={NEW_COLUMNS} rows={newly.rows} getRowKey={(r) => r.code} pageSize={8} density="compact" minWidth="480px"
              initialSort={{ key: "first", direction: "desc" }} onRowClick={(r) => onFocusArea(r.code, "village")}
              emptyState={<EmptyState>No village was hit for the first time in this period.</EmptyState>} />
          ))}
        </SectionCard>
      </div>

      <div className="col-span-12 xl:col-span-7">
        <SectionCard id="pareto" className="h-full" title="Concentration"
          subtitle={pareto && pareto.villages_hit ? `Top 10 villages = ${pareto.summary.top10_share_pct ?? 0}% of ${metricLabel.toLowerCase()}; half comes from ${pareto.summary.villages_for_50_pct} and 80% from ${pareto.summary.villages_for_80_pct} of ${formatNumber(pareto.villages_hit)} villages hit` : "Villages sorted by the metric, with the cumulative share of the total"}
          actions={<CsvButton filename={`concentration_${fileSuffix}`} disabled={!pareto}
            headers={["rank", "village", "village (ar)", "value", "cumulative %"]}
            rows={() => (pareto?.rows ?? []).map((r) => [r.rank, r.name_en, r.name_ar, r.value, r.cumulative_pct])} />}>
          {failed ?? (!pareto ? <Skeleton className="h-[520px]" /> : pareto.rows.length === 0 ? <EmptyState>Nothing recorded for these filters.</EmptyState> : (
            <>
              <ParetoChart data={pareto} metricLabel={metricLabel} height={520} />
              {pareto.rows.length > PARETO_CHART_LIMIT ? <p className="mt-1 text-caption text-text-muted">The chart shows the {PARETO_CHART_LIMIT} largest villages; the CSV has all {formatNumber(pareto.rows.length)}.</p> : null}
            </>
          ))}
        </SectionCard>
      </div>
    </>
  );
};
