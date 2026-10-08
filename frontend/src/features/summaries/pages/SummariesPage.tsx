import { useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, EmptyState, Input, Label, Select, type DataTableColumn, type SelectOption } from "../../../components/ui";
import { formatRelativeTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { SummaryReasonChips, SummaryWindow } from "../components/SummaryReviewTable";
import { useSummariesQuery } from "../hooks";
import { summaryStatusLabel } from "../logic";
import type { SummaryListItem } from "../types";

const PAGE_SIZE = 25;
const statusOptions: SelectOption[] = [
  { value: "parsed", label: "Waiting for reconciliation" },
  { value: "needs_review", label: "Needs review" },
  { value: "reconciled", label: "Reconciled" },
  { value: "failed", label: "Failed" },
];

export const SummariesPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const roleBase = roleBaseFromPath(location.pathname);
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const status = params.get("status") ?? "";
  const channel = params.get("channel") ?? "";
  const dateFrom = params.get("date_from") ?? "";
  const dateTo = params.get("date_to") ?? "";
  const includeHidden = params.get("show_hidden") === "true";
  const openOnly = params.get("open_task") === "true";

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setPage(1);
    setParams(next);
  };

  const { data, isLoading, isError, isFetching, refetch } = useSummariesQuery({
    status: status || undefined,
    channel: channel || undefined,
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
    hasOpenTask: openOnly ? true : undefined,
    includeHidden,
    page,
    pageSize: PAGE_SIZE,
  });
  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasFilters = Boolean(status || channel || dateFrom || dateTo || includeHidden || openOnly);

  const columns: Array<DataTableColumn<SummaryListItem>> = [
    { key: "channel", header: "Channel", render: (s) => <span className="font-semibold" dir="auto">{s.channel ?? "Unknown channel"}</span> },
    { key: "window", header: "Window", render: (s) => <SummaryWindow summary={s} /> },
    {
      key: "status",
      header: "Status",
      render: (s) => (
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label={summaryStatusLabel(s.status)} variant={s.status === "failed" ? "danger" : s.status === "reconciled" ? "success" : "neutral"} />
          {s.hidden ? <StatusBadge label="Hidden (fully matched)" variant="neutral" /> : null}
        </div>
      ),
    },
    {
      key: "items",
      header: "Items",
      render: (s) => (
        <span className="text-small tabular-nums">
          {s.item_count} <span className="text-text-muted">· {s.matched_count} matched · {s.created_count} created</span>
        </span>
      ),
    },
    { key: "reasons", header: "Review", render: (s) => (s.reasons.length ? <SummaryReasonChips reasons={s.reasons} /> : <span className="text-small text-text-muted">None</span>) },
    { key: "when", header: "Received", render: (s) => <span className="whitespace-nowrap text-small text-text-muted">{formatRelativeTime(s.created_at)}</span> },
  ];

  return (
    <div className="space-y-6">
      <section className="space-y-1">
        <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">Incident operations</p>
        <h1 className="text-h3 font-semibold text-text-primary">Summary bulletins</h1>
        <p className="text-small text-text-muted">
          Round-ups such as «ملخص الاعتداءات», reconciled against live incidents. Fully matched summaries stay hidden unless you show them.
          {isFetching ? " Refreshing…" : ""}
        </p>
      </section>

      <section className="grid gap-4 rounded-xl border border-border bg-surface-raised p-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-2">
          <Label htmlFor="summary-status-filter">Status</Label>
          <Select id="summary-status-filter" value={status} options={statusOptions} placeholder="All statuses" className="w-full" onChange={(v) => update("status", v)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="summary-channel-filter">Channel</Label>
          <Input id="summary-channel-filter" defaultValue={channel} placeholder="Exact channel name" onBlur={(event) => update("channel", event.target.value.trim())} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="summary-from-filter">From</Label>
          <Input id="summary-from-filter" type="date" value={dateFrom} onChange={(event) => update("date_from", event.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="summary-to-filter">To</Label>
          <Input id="summary-to-filter" type="date" value={dateTo} onChange={(event) => update("date_to", event.target.value)} />
        </div>
        <div className="flex flex-wrap items-center gap-4 sm:col-span-2 xl:col-span-4">
          <label className="flex items-center gap-2 text-small font-semibold">
            <input type="checkbox" checked={includeHidden} onChange={(event) => update("show_hidden", event.target.checked ? "true" : "")} className="h-4 w-4" />
            Show hidden (fully matched) summaries
          </label>
          <label className="flex items-center gap-2 text-small font-semibold">
            <input type="checkbox" checked={openOnly} onChange={(event) => update("open_task", event.target.checked ? "true" : "")} className="h-4 w-4" />
            Only with an open review task
          </label>
          {hasFilters ? (
            <Button type="button" variant="ghost" className="h-9" onClick={() => { setPage(1); setParams(new URLSearchParams()); }}>
              Clear filters
            </Button>
          ) : null}
        </div>
      </section>

      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(s) => String(s.id)}
        loading={isLoading}
        error={isError}
        clientSort={false}
        density="compact"
        minWidth="900px"
        onRowClick={(s) => navigate(`${roleBase}/summaries/${s.id}`)}
        emptyState={
          <EmptyState
            title={hasFilters ? "No matching summaries" : "No summaries yet"}
            description={hasFilters ? "Adjust or clear the filters to broaden the results." : "Summary bulletins appear here once the summary flow has processed one."}
          />
        }
        errorState={
          <div className="space-y-3 p-6 text-center">
            <EmptyState title="Could not load summaries" description="The summaries list could not be loaded." />
            <Button type="button" variant="secondary" onClick={() => void refetch()}>Try again</Button>
          </div>
        }
        actions={(s) => <Button type="button" variant="secondary" className="h-9" onClick={() => navigate(`${roleBase}/summaries/${s.id}`)}>Open</Button>}
      />

      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-between">
          <p className="text-small text-text-muted">Showing {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, total)} of {total}</p>
          <div className="flex gap-2">
            <Button type="button" variant="secondary" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <Button type="button" variant="secondary" disabled={page * PAGE_SIZE >= total} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
};
