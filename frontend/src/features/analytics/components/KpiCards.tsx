import { cn } from "../../../lib/cn";
import type { ReactNode } from "react";
import { deltaView, formatNumber, sparkPath } from "../mappers";
import type { Delta, KpisResponse, SeriesPoint, Split } from "../types";
import { ErrorBlock, Skeleton, errorMessage } from "./common";

const Spark = ({ points, color }: { points: SeriesPoint[]; color: string }) => (
  <svg viewBox="0 0 100 24" className="h-6 w-full" preserveAspectRatio="none" aria-hidden="true">
    <path d={sparkPath(points, 100, 24)} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
  </svg>
);

type CardProps = {
  title: string;
  delta: Delta;
  spark?: SeriesPoint[];
  color: string;
  split?: Split;
  neutral?: boolean;
  note?: ReactNode;
};

const KpiCard = ({ title, delta, spark, color, split, neutral, note }: CardProps) => {
  const view = deltaView(delta);
  const tone = neutral || view.direction === "flat" ? "text-text-muted" : view.direction === "up" ? "text-danger" : "text-success";
  return (
    <div className="group relative rounded-lg border border-card-border bg-card-bg p-4 shadow-raised focus-within:ring-2 focus-within:ring-focus-ring" tabIndex={split ? 0 : undefined}>
      <div className="text-small font-medium text-text-muted">{title}</div>
      <div className="mt-1 text-h2 font-semibold tabular-nums leading-none">{formatNumber(delta.current)}</div>
      <div className={cn("mt-1 text-caption font-medium tabular-nums", tone)} title={view.label}>
        <span aria-hidden="true">{view.direction === "up" ? "▲" : view.direction === "down" ? "▼" : "■"} </span>
        <span className="sr-only">{view.label}. </span>{view.text}
      </div>
      {spark ? <div className="mt-2"><Spark points={spark} color={color} /></div> : null}
      {note ? <div className="mt-1 text-caption text-text-muted">{note}</div> : null}
      {split ? (
        <div role="tooltip" className="invisible absolute left-3 top-full z-10 mt-1 w-52 rounded-md border border-border bg-surface-raised p-3 text-caption opacity-0 shadow-overlay transition-opacity group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100">
          <div className="mb-1 font-semibold">Breakdown</div>
          {([["Male", split.male], ["Female", split.female], ["Children", split.children], ["Unspecified", split.unspecified]] as const).map(([label, value]) => (
            <div key={label} className="flex justify-between tabular-nums"><span>{label}</span><span>{formatNumber(value)}</span></div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

export const KpiCards = ({ data, loading, error, onRetry, onOpenMethodology }: { data?: KpisResponse; loading: boolean; error: unknown; onRetry: () => void; onOpenMethodology: () => void }) => {
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) {
    return <div className="grid grid-cols-3 gap-4 xl:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-32" />)}</div>;
  }
  const breachDelta: Delta = data.air_breaches;
  const esc = data.escalation;
  const completeness = data.casualty_completeness;
  const completenessNote = completeness.pct === null
    ? "Casualty status is not available for these incidents."
    : <>Casualty figures are extracted from reports; {completeness.pct}% of incidents in this period have a casualty status. <button type="button" onClick={onOpenMethodology} className="text-brand-navy underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Methodology</button></>;
  return (
    <section aria-label="Key figures" className="space-y-2">
      <div className="grid grid-cols-3 gap-4 xl:grid-cols-6">
        <KpiCard title="Incidents" delta={data.incidents} spark={data.sparklines.incidents} color="#082d6f" />
        <KpiCard title="Deaths" delta={data.deaths} spark={data.sparklines.deaths} color="#9b2c2c" split={data.deaths} note={completenessNote} />
        <KpiCard title="Injuries" delta={data.injuries} spark={data.sparklines.injuries} color="#bc8e38" split={data.injuries} note={completenessNote} />
        <KpiCard title="Villages affected" delta={data.villages_affected} color="#009e73" neutral note={`${formatNumber(data.cazas_affected.current)} cazas`} />
        <KpiCard title="Air breaches" delta={breachDelta} spark={data.sparklines.breaches} color="#0072b2" note={data.air_breaches.by_type.map((t) => `${t.label.split(" ")[0]} ${t.current}`).join(" · ")} />
        <KpiCard title="Pending review" delta={{ current: data.pending_review, previous: 0, delta: 0, pct: null }} color="#7f8c8d" neutral note="Not in the headline" />
      </div>
      <p className="text-caption text-text-muted tabular-nums">
        Latest day ({esc.date}): <strong>{formatNumber(esc.today)}</strong> incidents vs a 30-day average of <strong>{esc.rolling_30d_daily_average}</strong>
        {esc.ratio !== null ? <> ({esc.ratio}×)</> : null}.
        {data.unattributed_shared_toll_incidents > 0 ? (
          <> {formatNumber(data.unattributed_shared_toll_incidents)} incident(s) carry a shared bulletin toll that is <em>not attributed to a specific village</em>; it is counted once.</>
        ) : null}
      </p>
    </section>
  );
};
