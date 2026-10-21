import { formatDate } from "../../../lib/formatters";
import { formatNumber } from "../mappers";
import type { PeakEntry, PeaksResponse } from "../types";
import { ErrorBlock, Skeleton, errorMessage } from "./common";

const Peak = ({ title, entry, unit }: { title: string; entry: PeakEntry; unit: "day" | "week" }) => (
  <div className="rounded-md border border-border p-3">
    <div className="text-caption font-semibold uppercase tracking-wide text-text-muted">{title}</div>
    {entry ? (
      <>
        <div className="mt-1 text-h3 font-semibold leading-none tabular-nums">{formatNumber(entry.value)}</div>
        <div className="text-caption text-text-muted">{unit === "week" ? "week of " : ""}{formatDate(entry.start)}</div>
        <ul className="mt-2 space-y-0.5">
          {entry.top_areas.map((a) => (
            <li key={a.code} className="flex justify-between gap-2 text-caption tabular-nums">
              <span className="truncate">{a.name_en} <span dir="rtl" lang="ar" className="text-text-muted">{a.name_ar}</span></span>
              <span>{formatNumber(a.value)}</span>
            </li>
          ))}
        </ul>
      </>
    ) : <div className="mt-2 text-small text-text-muted">No data in this period</div>}
  </div>
);

export const PeaksCards = ({ data, loading, error, onRetry }: { data?: PeaksResponse; loading: boolean; error: unknown; onRetry: () => void }) => {
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) return <Skeleton className="h-64" />;
  return (
    <div className="grid grid-cols-2 gap-3">
      <Peak title="Worst day · incidents" entry={data.incidents.day} unit="day" />
      <Peak title="Worst week · incidents" entry={data.incidents.week} unit="week" />
      <Peak title="Worst day · deaths" entry={data.deaths.day} unit="day" />
      <Peak title="Worst week · deaths" entry={data.deaths.week} unit="week" />
      <Peak title="Worst day · air breaches" entry={data.breaches.day} unit="day" />
      <Peak title="Worst week · air breaches" entry={data.breaches.week} unit="week" />
    </div>
  );
};
