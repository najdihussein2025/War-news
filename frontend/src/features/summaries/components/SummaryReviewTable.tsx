import { useNavigate } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, EmptyState, type DataTableColumn } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { useSummariesQuery } from "../hooks";
import { reasonLabel } from "../logic";
import type { SummaryListItem } from "../types";

export const SummaryWindow = ({ summary }: { summary: Pick<SummaryListItem, "window_start" | "window_end"> }) =>
  summary.window_start && summary.window_end ? (
    <span className="whitespace-nowrap text-small">
      {formatDateTime(summary.window_start)} <span className="text-text-muted">to</span> {formatDateTime(summary.window_end)}
    </span>
  ) : (
    <span className="text-small text-text-muted">Window not resolved</span>
  );

export const SummaryReasonChips = ({ reasons }: { reasons: SummaryListItem["reasons"] }) => (
  <div className="flex flex-wrap gap-1">
    {reasons.map((reason) => (
      <StatusBadge key={reason.type} label={`${reasonLabel(reason.type)} · ${reason.count}`} variant="warning" />
    ))}
  </div>
);

/** One row per open summary review task (never one per item). */
export const SummaryReviewTable = ({ roleBase }: { roleBase: string }) => {
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useSummariesQuery({ hasOpenTask: true, page: 1, pageSize: 100 });
  const open = (summary: SummaryListItem) => navigate(`${roleBase}/summaries/${summary.id}`);

  const columns: Array<DataTableColumn<SummaryListItem>> = [
    {
      key: "channel",
      header: "Channel",
      render: (summary) => <span className="font-semibold text-text-primary" dir="auto">{summary.channel ?? "Unknown channel"}</span>,
    },
    { key: "window", header: "Window", render: (summary) => <SummaryWindow summary={summary} /> },
    {
      key: "items",
      header: "Items",
      render: (summary) => (
        <span className="text-small tabular-nums">
          {summary.item_count} <span className="text-text-muted">· {summary.unresolved_count} unresolved</span>
        </span>
      ),
    },
    { key: "reasons", header: "Why it needs review", render: (summary) => <SummaryReasonChips reasons={summary.reasons} /> },
  ];

  return (
    <section className="space-y-3" aria-label="Summary review tasks">
      <div>
        <h2 className="text-h4 font-semibold text-text-primary">Summary review</h2>
        <p className="text-small text-text-muted">
          {data ? `${data.total} summar${data.total === 1 ? "y" : "ies"} waiting for a decision` : "Summaries with an open review task"}
        </p>
      </div>
      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        getRowKey={(summary) => String(summary.id)}
        loading={isLoading}
        error={isError}
        clientSort={false}
        density="compact"
        minWidth="760px"
        onRowClick={open}
        emptyState={<EmptyState title="No summaries to review" description="Every summary bulletin was matched or already reviewed." />}
        errorState={
          <div className="space-y-3 p-6 text-center">
            <EmptyState title="Could not load summaries" description="The summary review list could not be loaded." />
            <Button type="button" variant="secondary" onClick={() => void refetch()}>Try again</Button>
          </div>
        }
        actions={(summary) => (
          <Button type="button" className="h-9" onClick={() => open(summary)}>Review</Button>
        )}
      />
    </section>
  );
};
