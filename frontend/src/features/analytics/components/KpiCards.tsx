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

type Tone = "bad-up" | "good-up" | "neutral";

type CardProps = {
  title: string;
  delta: Delta;
  spark?: SeriesPoint[];
  color: string;
  split?: Split;
  tone?: Tone;
  note?: string;
  info?: ReactNode;
  /** Appended to the value, e.g. "%". */
  suffix?: string;
  /** Unit of the change when it is not a count, e.g. "pts". */
  deltaUnit?: string;
};

const KpiCard = ({ title, delta, spark, color, split, tone = "bad-up", note, info, suffix = "", deltaUnit }: CardProps) => {
  const view = deltaView(delta);
  const toneClass = tone === "neutral" || view.direction === "flat" ? "text-text-muted"
    : (view.direction === "up") === (tone === "bad-up") ? "text-danger" : "text-success";
  const text = deltaUnit ? `${delta.delta > 0 ? "+" : ""}${formatNumber(delta.delta)} ${deltaUnit}` : view.text;
  return (
    <div className="flex h-full min-w-0 flex-col rounded-lg border border-card-border bg-card-bg p-3 shadow-raised">
      <div className="flex min-h-6 items-center justify-between gap-1">
        <span className="truncate text-small font-medium text-text-muted" title={title}>{title}</span>
        {info ? <InfoTip label={`About ${title.toLowerCase()}`} align="right">{info}</InfoTip> : null}
      </div>
      <span className="mt-0.5 truncate text-h3 font-semibold leading-tight tabular-nums">{formatNumber(delta.current)}{suffix}</span>
      <span className={cn("truncate text-caption font-medium tabular-nums", toneClass)} title={view.label}>
        <span aria-hidden="true">{view.direction === "up" ? "▲" : view.direction === "down" ? "▼" : "■"} </span>
        <span className="sr-only">{view.label}. </span>{text}
      </span>
      <div className="mt-auto pt-1.5">
        {spark ? <Spark points={spark} color={color} /> : <div className="h-6" aria-hidden="true" />}
        {split ? <SplitLine split={split} /> : <p className="truncate text-caption text-text-muted" title={note}>{note ?? " "}</p>}
      </div>
    </div>
  );
};

/** Nine headline figures, each with its change vs the previous equal-length period. */
export const KpiCards = ({ data, loading, error, onRetry, onOpenMethodology }: { data?: KpisResponse; loading: boolean; error: unknown; onRetry: () => void; onOpenMethodology: () => void }) => {
  const grid = "grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-3 min-[1400px]:grid-cols-9";
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) {
    return <div className={grid}>{Array.from({ length: 9 }, (_, i) => <Skeleton key={i} className="h-[8.25rem]" />)}</div>;
  }
  const casualtyInfo = (
    <>
      {casualtyNote(data.casualty_completeness)}
      {" "}Figures are extracted from reports. Children are counted under children only; a toll with no type stated counts in the total only.{" "}
      <button type="button" onClick={onOpenMethodology} className="font-semibold text-brand-navy underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Methodology</button>
    </>
  );
  const verified = data.verified_pct;
  const verifiedDelta: Delta = { current: verified.current ?? 0, previous: verified.previous ?? 0, delta: verified.delta ?? 0, pct: null };
  return (
    <section aria-label="Key figures" className="space-y-1.5">
      <div className={grid}>
        <KpiCard title="Incidents" delta={data.incidents} spark={data.sparklines.incidents} color="#082d6f" note={`prev. ${formatNumber(data.incidents.previous)}`} />
        <KpiCard title="Deaths" delta={data.deaths} spark={data.sparklines.deaths} color="#9b2c2c" split={data.deaths} info={casualtyInfo} />
        <KpiCard title="Injuries" delta={data.injuries} spark={data.sparklines.injuries} color="#bc8e38" split={data.injuries} info={casualtyInfo} />
        <KpiCard title="Villages affected" delta={data.villages_affected} spark={data.sparklines.villages} color="#009e73" tone="neutral" note="with ≥ 1 incident" />
        <KpiCard title="Cazas affected" delta={data.cazas_affected} spark={data.sparklines.cazas} color="#56b4e9" tone="neutral" note="with ≥ 1 incident" />
        <KpiCard title="Air breaches" delta={data.air_breaches} spark={data.sparklines.breaches} color="#0072b2" note={data.air_breaches.by_type.map((t) => `${t.label.split(" ")[0]} ${t.current}`).join(" · ")} />
        <KpiCard title="Daily average" delta={data.daily_average} spark={data.sparklines.incidents} color="#082d6f" note={`incidents / day over ${data.period.days} d`} />
        <KpiCard title="Accepted (not pending)" delta={verifiedDelta} suffix={verified.current === null ? "" : "%"} deltaUnit="pts" color="#009e73" tone="good-up"
          info="Share of incidents counted in the headline: auto-processed or verified, excluding pending review."
          note={`Human-verified: ${formatNumber(verified.human_verified)}`} />
        <KpiCard title="Pending review" delta={data.pending_review_delta ?? { current: data.pending_review, previous: 0, delta: 0, pct: null }} spark={data.sparklines.pending} color="#7f8c8d" tone="neutral" note="not in the headline" />
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
