import { useState } from "react";
import { Dialog } from "../../../components/ui/Dialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { formatDate } from "../../../lib/formatters";
import { familyColor } from "../colors";
import { toApiParams } from "../filters";
import { useIncidents } from "../hooks";
import { formatNumber, hasArabic, villageLabel } from "../mappers";
import type { AnalyticsFilters } from "../types";
import { ErrorBlock, FamilyDot, Skeleton, errorMessage } from "./common";

const PAGE = 25;

export const DrilldownDrawer = ({ filters, title, onClose }: { filters: AnalyticsFilters; title: string; onClose: () => void }) => {
  const [page, setPage] = useState(1);
  const params = toApiParams({ ...filters, metric: filters.metric === "breaches" ? "incidents" : filters.metric });
  const query = useIncidents(params, page, true);
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <Dialog title={title} eyebrow="Incidents behind this number" onClose={onClose} size="panel">
      <p className="mb-3 text-small text-text-muted tabular-nums" aria-live="polite">{query.data ? `${formatNumber(total)} incident(s) · page ${page} of ${pages}` : "Loading…"}</p>
      {query.error && !query.data ? <ErrorBlock message={errorMessage(query.error)} onRetry={() => void query.refetch()} /> : null}
      {!query.data && !query.error ? <div className="space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div> : null}
      {query.data && query.data.items.length === 0 ? <EmptyState title="No incidents" description="Nothing matches these filters." className="min-h-32" /> : null}
      <ul className="divide-y divide-border">
        {query.data?.items.map((item) => (
          <li key={item.id} className="py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-small font-semibold">{villageLabel(item)} {item.village_ar ? <span dir="rtl" lang="ar" className="font-normal text-text-muted">{item.village_ar}</span> : null}</span>
              <span className="text-caption text-text-muted tabular-nums">{formatDate(item.event_date)}{item.event_time ? ` ${item.event_time.slice(0, 5)}` : ""}</span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-caption">
              <span className="flex items-center gap-1.5"><FamilyDot color={familyColor(item.family)} />{item.action_en}</span>
              <span className="rounded bg-surface-muted px-1.5">{item.verification_status.replace("_", " ")}</span>
              {item.bucket === "pending" ? <span className="rounded bg-brand-gold-soft px-1.5">pending review</span> : null}
              {item.source === "archive" ? <span className="rounded bg-sky-100 px-1.5">archive</span> : null}
              <span className="tabular-nums">Deaths {item.deaths} · Injuries {item.injuries}</span>
            </div>
            <p className="mt-1 text-small text-text-primary" dir={hasArabic(item.khabar_excerpt) ? "rtl" : "ltr"} lang={hasArabic(item.khabar_excerpt) ? "ar" : undefined}>{item.khabar_excerpt}</p>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex items-center justify-between">
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="h-9 rounded-md border border-border px-3 text-small disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Previous</button>
        <button type="button" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="h-9 rounded-md border border-border px-3 text-small disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Next</button>
      </div>
    </Dialog>
  );
};
