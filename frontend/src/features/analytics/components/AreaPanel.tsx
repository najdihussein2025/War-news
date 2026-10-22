import { formatDate } from "../../../lib/formatters";
import { familyColor } from "../colors";
import { toApiParams } from "../filters";
import { useArea } from "../hooks";
import { casualtyNote, formatNumber, sparkPath } from "../mappers";
import type { AnalyticsFilters, Level } from "../types";
import { ErrorBlock, FamilyDot, Skeleton, errorMessage } from "./common";

type Props = {
  code: string;
  filters: AnalyticsFilters;
  onClose: () => void;
  onFocusArea: (code: string, level: Level) => void;
  onViewIncidents: (code: string) => void;
  onOpenMethodology: () => void;
  /** "overlay" floats over the map's right edge; "column" fills the side column next to it. */
  variant?: "overlay" | "column";
};

export const AreaPanel = ({ code, filters, onClose, onFocusArea, onViewIncidents, onOpenMethodology, variant = "overlay" }: Props) => {
  const params = toApiParams(filters, { areaCode: null, metric: "incidents" });
  const query = useArea(code, params);
  const data = query.data;
  const maxFamily = Math.max(...(data?.families.map((f) => f.incidents) ?? [1]), 1);

  return (
    <aside aria-label="Area profile" className={variant === "overlay"
      ? "absolute bottom-52 right-3 top-28 z-20 flex w-[340px] max-w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-lg border border-border bg-surface-raised shadow-overlay"
      : "flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-card-border bg-card-bg shadow-raised"}>
      <div className="flex items-start justify-between gap-2 border-b border-border p-3">
        <div className="min-w-0">
          {data ? (
            <>
              <h3 dir="rtl" lang="ar" className="text-h4 font-semibold">{data.area.name_ar || data.area.name_en}</h3>
              <p className="text-small text-text-muted">{data.area.name_en} · <span className="capitalize">{data.area.level}</span>{data.area.parent_name_en ? ` · ${data.area.parent_name_en}` : ""}</p>
              {data.area.is_disputed ? <p className="mt-1 inline-block rounded bg-brand-gold-soft px-1.5 text-caption">Disputed area</p> : null}
            </>
          ) : <Skeleton className="h-10 w-48" />}
        </div>
        <button type="button" onClick={onClose} aria-label="Close area profile" className="h-8 w-8 shrink-0 rounded-md hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">✕</button>
      </div>
      <div className="flex-1 space-y-4 overflow-auto p-3">
        {query.error && !data ? <ErrorBlock message={errorMessage(query.error)} onRetry={() => void query.refetch()} /> : null}
        {!data && !query.error ? <Skeleton className="h-64" /> : null}
        {data ? (
          <>
            <dl className="grid grid-cols-3 gap-2 text-center">
              {([["Incidents", data.totals.incidents], ["Deaths", data.totals.deaths], ["Injuries", data.totals.injuries]] as const).map(([label, value]) => (
                <div key={label} className="rounded-md bg-surface-muted p-2"><dt className="text-caption text-text-muted">{label}</dt><dd className="text-h4 font-semibold tabular-nums">{formatNumber(value)}</dd></div>
              ))}
            </dl>
            {data.casualty_completeness.incidents > 0 ? (
              <p className="text-caption text-text-muted">{casualtyNote(data.casualty_completeness)} <button type="button" onClick={onOpenMethodology} className="text-brand-navy underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Methodology</button></p>
            ) : null}
            <p className="text-caption text-text-muted tabular-nums">
              {data.air_breaches.total > 0 ? `${formatNumber(data.air_breaches.total)} air breaches (${data.air_breaches.by_type.map((t) => `${t.label} ${t.value}`).join(", ")}). ` : "No air breaches. "}
              {data.pending_review > 0 ? `${formatNumber(data.pending_review)} pending review. ` : ""}
              {data.first_last_hit.first_date ? `First hit ${formatDate(data.first_last_hit.first_date)}, latest ${formatDate(data.first_last_hit.last_date ?? data.first_last_hit.first_date)}.` : ""}
            </p>
            <section aria-label="Actions"><h4 className="mb-1 text-small font-semibold">By action</h4>
              {data.families.length === 0 ? <p className="text-small text-text-muted">No incidents in this period.</p> : (
                <ul className="space-y-1">
                  {data.families.map((f) => (
                    <li key={f.code} className="grid grid-cols-[1fr_2.5rem] items-center gap-2 text-caption">
                      <div><div className="flex items-center gap-1.5"><FamilyDot color={familyColor(f.code)} />{f.name_en}</div>
                        <div className="mt-0.5 h-2 rounded-sm bg-gray-100"><div className="h-2 rounded-sm" style={{ width: `${(f.incidents / maxFamily) * 100}%`, background: familyColor(f.code) }} /></div></div>
                      <span className="text-right tabular-nums">{formatNumber(f.incidents)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-label="Timeline"><h4 className="mb-1 text-small font-semibold">Daily incidents</h4>
              <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-14 w-full rounded-md bg-surface-muted" role="img" aria-label="Daily incidents sparkline">
                <path d={sparkPath(data.timeline.incidents, 100, 28)} fill="none" stroke="#082d6f" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
              </svg>
            </section>
            {data.top_children.rows.length ? (
              <section aria-label="Top areas inside"><h4 className="mb-1 text-small font-semibold">Most hit {data.top_children.level === "village" ? "villages" : "cazas"}</h4>
                <ol className="space-y-0.5">
                  {data.top_children.rows.slice(0, 8).map((r) => (
                    <li key={r.code}><button type="button" onClick={() => onFocusArea(r.code, r.level)} className="flex w-full justify-between gap-2 rounded px-1 py-0.5 text-left text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
                      <span className="truncate">{r.name_en} <span dir="rtl" lang="ar" className="text-text-muted">{r.name_ar}</span></span><span className="tabular-nums">{formatNumber(r.incidents)}</span></button></li>
                  ))}
                </ol>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
      <div className="border-t border-border p-3">
        <button type="button" onClick={() => onViewIncidents(code)} className="h-9 w-full rounded-md bg-brand-navy text-small font-semibold text-text-inverse hover:bg-brand-navy-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">View incidents</button>
      </div>
    </aside>
  );
};
