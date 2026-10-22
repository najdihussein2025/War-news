import { formatDate } from "../../../lib/formatters";
import { formatNumber } from "../mappers";
import type { PeakEntry, PeaksResponse } from "../types";
import { ErrorBlock, Skeleton, errorMessage } from "./common";

const METRICS = [["incidents", "Incidents"], ["deaths", "Deaths"], ["breaches", "Air breaches"]] as const;
const UNITS = [["day", "worst day"], ["week", "worst week"]] as const;

const Peak = ({ title, entry, unit }: { title: string; entry: PeakEntry; unit: "day" | "week" }) => {
  const areas = entry?.top_areas.map((a) => `${a.name_en} ${formatNumber(a.value)}`).join(" · ") ?? "";
  return (
    <article className="flex h-full min-w-0 flex-col rounded-lg border border-card-border bg-card-bg p-3 shadow-raised">
      <h3 className="truncate text-caption font-semibold uppercase tracking-wide text-text-muted">{title}</h3>
      {entry ? (
        <>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-h4 font-semibold leading-none tabular-nums">{formatNumber(entry.value)}</span>
            <span className="truncate text-caption tabular-nums text-text-muted">
              {unit === "week" ? "wk of " : ""}{formatDate(entry.start)}
              {entry.low_coverage_days > 0 ? <span title={`${entry.low_coverage_days} low- or no-coverage day(s) in this peak`}> *</span> : null}
            </span>
          </div>
          <p className="mt-1.5 truncate border-t border-border pt-1.5 text-caption tabular-nums" title={areas}>{areas || "—"}</p>
        </>
      ) : <p className="mt-1 text-small text-text-muted">No data in this period</p>}
    </article>
  );
};

/** One horizontal row: worst day and week for incidents, deaths and air breaches, with the top cazas. */
export const PeaksCards = ({ data, loading, error, onRetry }: { data?: PeaksResponse; loading: boolean; error: unknown; onRetry: () => void }) => {
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) {
    return <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[6.25rem]" />)}</div>;
  }
  const flagged = METRICS.some(([m]) => UNITS.some(([u]) => (data[m][u]?.low_coverage_days ?? 0) > 0));
  return (
    <div className="space-y-1.5">
      <div className="grid auto-rows-fr grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {METRICS.flatMap(([metric, label]) => UNITS.map(([unit, unitLabel]) => (
          <Peak key={`${metric}-${unit}`} title={`${label} · ${unitLabel}`} entry={data[metric][unit]} unit={unit} />
        )))}
      </div>
      {flagged ? <p className="text-caption text-text-muted">* Includes one or more days with low or no message coverage; values may be incomplete.</p> : null}
    </div>
  );
};
