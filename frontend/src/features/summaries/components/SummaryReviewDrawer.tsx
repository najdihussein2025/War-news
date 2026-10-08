import { useState } from "react";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Card, Dialog, EmptyState } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { SummaryItemsTable } from "./SummaryItemsTable";
import { SummaryResolveForm } from "./SummaryResolveForm";
import { SummaryReasonChips, SummaryWindow } from "./SummaryReviewTable";
import { SummaryTextView } from "./SummaryTextView";
import { useSummaryQuery } from "../hooks";
import { summaryStatusLabel } from "../logic";

type Props = { summaryId: number; roleBase: string; onClose: () => void };

/** The review surface lives in Incidents; it is intentionally not a standalone route. */
export const SummaryReviewDrawer = ({ summaryId, roleBase, onClose }: Props) => {
  const { data: summary, isLoading, isError, refetch } = useSummaryQuery(summaryId);
  const [focusedItemId, setFocusedItemId] = useState<number | null>(null);
  return <Dialog title="Summary review" eyebrow="Summary bulletin" size="xl" onClose={onClose}>
    {isLoading ? <div className="h-64 animate-pulse rounded bg-surface-muted" /> : null}
    {isError || !summary ? <div className="space-y-3"><EmptyState title="Could not load this summary" description="It may not exist, or the request failed." /><Button type="button" variant="secondary" onClick={() => void refetch()}>Try again</Button></div> : null}
    {summary ? <div className="space-y-6">
      <section className="space-y-3"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div className="space-y-1"><h2 className="text-h3 font-semibold text-text-primary" dir="auto">{summary.channel ?? "Unknown channel"}</h2><SummaryWindow summary={summary} /></div><div className="flex flex-wrap items-center gap-2"><StatusBadge label={summaryStatusLabel(summary.status)} variant={summary.status === "failed" ? "danger" : summary.status === "reconciled" ? "success" : "neutral"} />{summary.hidden ? <StatusBadge label="Hidden (fully matched)" variant="neutral" /> : null}{summary.has_open_task ? <SummaryReasonChips reasons={summary.reasons} /> : null}</div></div>{summary.last_error ? <p className="rounded-md border border-warning/40 bg-surface px-3 py-2 text-small text-text-primary">Note: {summary.last_error}</p> : null}{summary.reposts.length ? <p className="text-small text-text-muted">Also posted by {summary.reposts.map((repost) => repost.channel ?? "unknown").join(", ")} · {formatDateTime(summary.reposts[0].created_at)}</p> : null}</section>
      <SummaryResolveForm summary={summary} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]"><Card className="space-y-3 p-4"><h3 className="text-h4 font-semibold text-text-primary">Bulletin text</h3><SummaryTextView text={summary.raw_text} items={summary.items} focusedItemId={focusedItemId} onFocusItem={setFocusedItemId} /></Card><Card className="space-y-3 p-4"><h3 className="text-h4 font-semibold text-text-primary">Items ({summary.items.length})</h3><SummaryItemsTable items={summary.items} roleBase={roleBase} focusedItemId={focusedItemId} onFocusItem={setFocusedItemId} /></Card></div>
    </div> : null}
  </Dialog>;
};
