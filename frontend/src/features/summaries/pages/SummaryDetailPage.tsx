import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Card, EmptyState } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { SummaryItemsTable } from "../components/SummaryItemsTable";
import { SummaryResolveForm } from "../components/SummaryResolveForm";
import { SummaryReasonChips, SummaryWindow } from "../components/SummaryReviewTable";
import { SummaryTextView } from "../components/SummaryTextView";
import { useSummaryQuery } from "../hooks";
import { summaryStatusLabel } from "../logic";

export const SummaryDetailPage = () => {
  const { summaryId } = useParams();
  const location = useLocation();
  const roleBase = roleBaseFromPath(location.pathname);
  const id = summaryId ? Number(summaryId) : undefined;
  const { data: summary, isLoading, isError, refetch } = useSummaryQuery(id);
  const [focusedItemId, setFocusedItemId] = useState<number | null>(null);

  const back = (
    <Link to={`${roleBase}/summaries`} className="text-small font-semibold text-accent underline-offset-2 hover:underline">
      ← All summaries
    </Link>
  );

  if (isLoading) {
    return (
      <div className="space-y-4" role="status" aria-live="polite">
        {back}
        <div className="h-8 w-64 animate-pulse rounded bg-surface-muted" />
        <div className="h-64 animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (isError || !summary) {
    return (
      <div className="space-y-4">
        {back}
        <EmptyState title="Could not load this summary" description="It may not exist, or the request failed." />
        <div className="text-center"><Button type="button" variant="secondary" onClick={() => void refetch()}>Try again</Button></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        {back}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">Summary bulletin</p>
            <h1 className="text-h3 font-semibold text-text-primary" dir="auto">{summary.channel ?? "Unknown channel"}</h1>
            <SummaryWindow summary={summary} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={summaryStatusLabel(summary.status)} variant={summary.status === "failed" ? "danger" : summary.status === "reconciled" ? "success" : "neutral"} />
            {summary.hidden ? <StatusBadge label="Hidden (fully matched)" variant="neutral" /> : null}
            {summary.has_open_task ? <SummaryReasonChips reasons={summary.reasons} /> : null}
          </div>
        </div>
        {summary.last_error ? (
          <p className="rounded-md border border-warning/40 bg-surface px-3 py-2 text-small text-text-primary" role="status">
            Note: {summary.last_error}
          </p>
        ) : null}
        {summary.reposts.length ? (
          <p className="text-small text-text-muted">
            Also posted by {summary.reposts.map((repost) => repost.channel ?? "unknown").join(", ")} ·{" "}
            {formatDateTime(summary.reposts[0].created_at)}
          </p>
        ) : null}
      </section>

      <SummaryResolveForm summary={summary} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card className="space-y-3 p-4">
          <h2 className="text-h4 font-semibold text-text-primary">Bulletin text</h2>
          <SummaryTextView text={summary.raw_text} items={summary.items} focusedItemId={focusedItemId} onFocusItem={setFocusedItemId} />
        </Card>
        <Card className="space-y-3 p-4">
          <h2 className="text-h4 font-semibold text-text-primary">Items ({summary.items.length})</h2>
          <SummaryItemsTable items={summary.items} roleBase={roleBase} focusedItemId={focusedItemId} onFocusItem={setFocusedItemId} />
        </Card>
      </div>
    </div>
  );
};
