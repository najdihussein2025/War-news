import { formatDate } from "../../../lib/formatters";
import { formatNumber } from "../mappers";
import type { PeakEntry, PeaksResponse } from "../types";
import { ErrorBlock, Skeleton, errorMessage } from "./common";

const Peak = ({ title, entry, unit }: { title: string; entry: PeakEntry; unit: "day" | "week" }) => (
  <article className="rounded-lg border border-border bg-surface-raised p-3 shadow-sm">
    <div className="text-caption font-semibold uppercase tracking-wide text-text-muted">{title}</div>
    {entry ? (
      <>
        <div className="mt-1 text-h3 font-semibold leading-none tabular-nums">{formatNumber(entry.value)}</div>
        <div className="text-caption text-text-muted">{unit === "week" ? "week of " : ""}{formatDate(entry.start)}{entry.low_coverage_days > 0 ? <span title={`${entry.low_coverage_days} low- or no-coverage day(s) in this peak`}> *</span> : null}</div>
        <ul className="mt-2 space-y-1 border-t border-border pt-2">
          {entry.top_areas.map((a) => (
            <li key={a.code} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 text-caption tabular-nums">
              <span className="min-w-0 truncate"><span>{a.name_en}</span>{a.name_ar ? <span dir="rtl" lang="ar" className="ml-1 text-text-muted">{a.name_ar}</span> : null}</span>
              <span className="font-semibold text-text-primary">{formatNumber(a.value)}</span>
            </li>
          ))}
        </ul>
      </>
    ) : <div className="mt-2 text-small text-text-muted">No data in this period</div>}
  </article>
);

export const PeaksCards = ({ data, loading, error, onRetry }: { data?: PeaksResponse; loading: boolean; error: unknown; onRetry: () => void }) => {
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-3">
      {(["incidents", "deaths", "breaches"] as const).map((metric) => (
        <section key={metric} aria-label={`${metric} peaks`}>
          <h3 className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-text-muted">{metric === "breaches" ? "Air breaches" : metric}</h3>
          <div className="grid grid-cols-2 gap-2">
            <Peak title="Worst day" entry={data[metric].day} unit="day" />
            <Peak title="Worst week" entry={data[metric].week} unit="week" />
          </div>
        </section>
      ))}
      <p className="text-caption text-text-muted">* Includes one or more days with low or no message coverage; values may be incomplete.</p>
    </div>
  );
};
