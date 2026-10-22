import { cn } from "../../../lib/cn";
import type { ReactNode } from "react";
import { formatDate } from "../../../lib/formatters";
import { casualtyNote, deltaView, formatNumber, sparkPath } from "../mappers";
import type { Delta, Escalation, EscalationDay, KpisResponse, SeriesPoint, Split } from "../types";
import { ErrorBlock, InfoTip, Skeleton, errorMessage } from "./common";

const Spark = ({ points, color }: { points: SeriesPoint[]; color: string }) => (
  <svg viewBox="0 0 100 24" className="h-6 w-full" preserveAspectRatio="none" aria-hidden="true">
    <path d={sparkPath(points, 100, 24)} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
  </svg>
);

/** Male / female / children / unspecified on one line; always visible (no hover-only data). */
const SplitLine = ({ split }: { split: Split }) => {
  const parts: Array<[string, string, number]> = [
    ["M", "Male", split.male], ["F", "Female", split.female], ["Ch", "Children", split.children], ["n/s", "Type not stated", split.unspecified],
  ];
  return (
    <p className="truncate text-caption tabular-nums text-text-muted" title={parts.map(([, long, v]) => `${long} ${v}`).join(" · ")}>
      {parts.map(([short, long, value], i) => (
        <span key={short}>{i > 0 ? " · " : ""}<abbr title={long} className="no-underline">{short}</abbr> {formatNumber(value)}</span>
      ))}
    </p>
  );
};

/** Latest complete day vs the 30 days before it; a day still being ingested is named, never shown as 0×. */
const EscalationLine = ({ escalation }: { escalation: Escalation }) => {
  const { latest, last_complete: complete } = escalation;
  if (!latest) return <>No incident data yet.</>;
  const day = (d: EscalationDay, label: string) => (
    <>{label} ({formatDate(d.date)}): <strong>{formatNumber(d.value)}</strong> incidents vs a 30-day average of <strong>{d.average_30d}</strong>{d.ratio !== null ? <> ({d.ratio}×)</> : null}.</>
  );
  return (
    <>
      {complete ? day(complete, "Latest complete day") : <>No complete day in the last week.</>}
      {latest.incomplete ? <> {formatDate(latest.date)} is still being processed ({formatNumber(latest.value)} so far).</> : null}
      {latest.date < escalation.requested_date ? <> No data yet after {formatDate(latest.date)}.</> : null}
    </>
  );
};

type CardProps = {
  title: string;
  delta: Delta;
  spark?: SeriesPoint[];
  color: string;
  split?: Split;
  neutral?: boolean;
  note?: string;
  info?: ReactNode;
};

const KpiCard = ({ title, delta, spark, color, split, neutral, note, info }: CardProps) => {
  const view = deltaView(delta);
  const tone = neutral || view.direction === "flat" ? "text-text-muted" : view.direction === "up" ? "text-danger" : "text-success";
  return (
    <div className="flex h-full min-w-0 flex-col rounded-lg border border-card-border bg-card-bg p-3 shadow-raised">
      <div className="flex min-h-6 items-center justify-between gap-1">
        <span className="truncate text-small font-medium text-text-muted">{title}</span>
        {info ? <InfoTip label={`About ${title.toLowerCase()}`} align="right">{info}</InfoTip> : null}
      </div>
      <div className="mt-0.5 flex items-baseline justify-between gap-2">
        <span className="text-h3 font-semibold leading-none tabular-nums">{formatNumber(delta.current)}</span>
        <span className={cn("truncate text-caption font-medium tabular-nums", tone)} title={view.label}>
          <span aria-hidden="true">{view.direction === "up" ? "▲" : view.direction === "down" ? "▼" : "■"} </span>
          <span className="sr-only">{view.label}. </span>{view.text}
        </span>
      </div>
      <div className="mt-auto pt-2">
        {spark ? <Spark points={spark} color={color} /> : <div className="h-6" aria-hidden="true" />}
        {split ? <SplitLine split={split} /> : <p className="truncate text-caption text-text-muted" title={note}>{note ?? " "}</p>}
      </div>
    </div>
  );
};

export const KpiCards = ({ data, loading, error, onRetry, onOpenMethodology }: { data?: KpisResponse; loading: boolean; error: unknown; onRetry: () => void; onOpenMethodology: () => void }) => {
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) {
    return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[7.25rem]" />)}</div>;
  }
  const breachDelta: Delta = data.air_breaches;
  const casualtyInfo = (
    <>
      {casualtyNote(data.casualty_completeness)}
      {" "}Figures are extracted from reports. Children are counted under children only; a toll with no type stated counts in the total only.{" "}
      <button type="button" onClick={onOpenMethodology} className="font-semibold text-brand-navy underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Methodology</button>
    </>
  );
  return (
    <section aria-label="Key figures" className="space-y-1.5">
      <div className="grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <KpiCard title="Incidents" delta={data.incidents} spark={data.sparklines.incidents} color="#082d6f" note={`vs ${formatNumber(data.incidents.previous)} in the previous ${data.period.days} days`} />
        <KpiCard title="Deaths" delta={data.deaths} spark={data.sparklines.deaths} color="#9b2c2c" split={data.deaths} info={casualtyInfo} />
        <KpiCard title="Injuries" delta={data.injuries} spark={data.sparklines.injuries} color="#bc8e38" split={data.injuries} info={casualtyInfo} />
        <KpiCard title="Villages affected" delta={data.villages_affected} color="#009e73" neutral note={`${formatNumber(data.cazas_affected.current)} cazas affected`} />
        <KpiCard title="Air breaches" delta={breachDelta} spark={data.sparklines.breaches} color="#0072b2" note={data.air_breaches.by_type.map((t) => `${t.label.split(" ")[0]} ${t.current}`).join(" · ")} />
        <KpiCard title="Pending review" delta={{ current: data.pending_review, previous: 0, delta: 0, pct: null }} color="#7f8c8d" neutral note="Not in the headline figures" />
      </div>
      <p className="text-caption text-text-muted tabular-nums">
        <EscalationLine escalation={data.escalation} />
        {data.unattributed_shared_toll_incidents > 0 ? (
          <> {formatNumber(data.unattributed_shared_toll_incidents)} incident(s) carry a shared bulletin toll that is <em>not attributed to a specific village</em>; it is counted once.</>
        ) : null}
      </p>
    </section>
  );
};
