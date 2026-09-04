import { useState } from "react";
import { Navigate, NavLink, useLocation, useParams, useSearchParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, Dialog, EmptyState, Input, Label, type DataTableColumn } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { formatDateTime } from "../../../lib/formatters";
import { useDebounce } from "../../../hooks/useDebounce";
import { useSourcesQuery } from "../../sources/hooks";
import { useAuditLogsQuery, useIngestionLogQuery, useIngestionLogsQuery, useLoginLogsQuery, usePipelineHealthQuery, useRetryIngestionMutation } from "../hooks";
import type { AuditLog, IngestionLog, IngestionStatus, LoginLog, PipelineLatencyCohort, PipelineStageQueueDepth } from "../types";

const logTabs = [
  { label: "Audit", value: "audit" },
  { label: "Login", value: "login" },
  { label: "Ingestion", value: "ingestion" },
];

const auditTextValue = (values: Record<string, unknown> | null, key: string) => {
  const value = values?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

const AuditTarget = ({ row }: { row: AuditLog }) => {
  if (row.target_type !== "account") {
    return <div><span className="break-all">{row.target}</span><p className="text-caption text-text-muted">{row.target_type}</p></div>;
  }

  const currentValues = row.new_values ?? row.old_values;
  const fullName = auditTextValue(currentValues, "full_name");
  const username = auditTextValue(currentValues, "username");
  const label = fullName ?? username ?? "Account";

  return <div><p className="font-semibold text-text-primary">{label}</p>{username && username !== label ? <p className="text-caption text-text-muted">@{username}</p> : null}</div>;
};

const AuditTable = () => {
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const pageSize = 25;
  const debouncedSearch = useDebounce(search);
  const { data, isLoading, isError } = useAuditLogsQuery({ search: debouncedSearch, action, dateFrom, dateTo, page, pageSize });
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  const columns: Array<DataTableColumn<AuditLog>> = [
    { key: "action", header: "Action", render: (row) => <span className="font-semibold text-text-primary">{row.action}</span> },
    { key: "by", header: "Performed by", render: (row) => <div>{row.performed_by}<p className="text-caption text-text-muted">{row.ip || "IP unavailable"}</p></div> },
    { key: "target", header: "Target", render: (row) => <AuditTarget row={row} /> },
    { key: "time", header: "Login Date & Time", render: (row) => formatDateTime(row.timestamp) },
    { key: "diff", header: "Changes", render: (row) => expandedId === row.id ? <pre className="max-w-xl overflow-x-auto whitespace-pre-wrap rounded-md border border-border bg-surface p-3 text-caption text-text-muted">{JSON.stringify({ before: row.old_values, after: row.new_values }, null, 2)}</pre> : <span className="text-text-muted">Collapsed</span> },
  ];
  return <div className="space-y-4"><div className="grid gap-3 rounded-lg border border-border bg-surface-raised p-4 md:grid-cols-4"><div className="space-y-2"><Label htmlFor="audit-search">Search</Label><Input id="audit-search" placeholder="Action, user, or target" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></div><div className="space-y-2"><Label htmlFor="audit-action">Action</Label><Input id="audit-action" placeholder="e.g. user.updated" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} /></div><div className="space-y-2"><Label htmlFor="audit-from">From</Label><Input id="audit-from" type="date" max={dateTo || undefined} value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} /></div><div className="space-y-2"><Label htmlFor="audit-to">To</Label><Input id="audit-to" type="date" min={dateFrom || undefined} value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} /></div></div><DataTable columns={columns} rows={data?.items ?? []} getRowKey={(row) => row.id} loading={isLoading} error={isError} clientSort={false} minWidth="1050px" emptyState={<EmptyState title="No audit logs" description="Administrative changes will appear here." />} errorState={<EmptyState title="Could not load audit logs" description="Check the API connection and database migration." />} actions={(row) => <Button type="button" variant="secondary" onClick={() => setExpandedId((id) => id === row.id ? null : row.id)}>{expandedId === row.id ? "Collapse" : "Expand"}</Button>} /><div className="flex flex-wrap items-center justify-between gap-3 text-small text-text-muted"><span>{data?.total ?? 0} results</span><div className="flex items-center gap-2"><Button type="button" variant="secondary" disabled={page <= 1 || isLoading} onClick={() => setPage((p) => p - 1)}>Previous</Button><span>Page {page} of {totalPages}</span><Button type="button" variant="secondary" disabled={page >= totalPages || isLoading} onClick={() => setPage((p) => p + 1)}>Next</Button></div></div></div>;
};

const LoginTable = () => {
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [result, setResult] = useState<"success" | "failure" | "all">(
    searchParams.get("result") === "failure" ? "failure" : "success",
  );
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const debouncedSearch = useDebounce(search);
  const { data, isLoading, isError } = useLoginLogsQuery({
    search: debouncedSearch,
    result,
    dateFrom,
    dateTo,
    page,
    pageSize,
  });
  const rows = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  const resetPage = () => setPage(1);
  const columns: Array<DataTableColumn<LoginLog>> = [
    { key: "username", header: "Username", render: (row) => <span className={cn("font-semibold", row.success ? "text-text-primary" : "text-danger")}>{row.username}</span>, sortValue: (row) => row.username },
    { key: "time", header: "Login date & time", render: (row) => formatDateTime(row.timestamp), sortValue: (row) => new Date(row.timestamp).getTime() },
    { key: "result", header: "Result", render: (row) => <StatusBadge label={row.success ? "Success" : "Failure"} variant={row.success ? "success" : "danger"} />, sortValue: (row) => row.success ? 1 : 0 },
    { key: "ip", header: "IP", render: (row) => row.ip, sortValue: (row) => row.ip },
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-surface-raised p-4 md:grid-cols-4">
        <div className="space-y-2"><Label htmlFor="login-search">Search</Label><Input
          id="login-search"
          placeholder="Search username or IP"
          value={search}
          onChange={(event) => { setSearch(event.target.value); resetPage(); }}
        /></div>
        <div className="space-y-2"><Label htmlFor="login-result">Result</Label><select id="login-result" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3" value={result} onChange={(event) => { setResult(event.target.value as "success" | "failure" | "all"); resetPage(); }}><option value="all">All results</option><option value="success">Successful</option><option value="failure">Failed</option></select></div>
        <div className="space-y-2"><Label htmlFor="login-from">From</Label><Input
          id="login-from"
          type="date"
          value={dateFrom}
          max={dateTo || undefined}
          onChange={(event) => { setDateFrom(event.target.value); resetPage(); }}
        /></div>
        <div className="space-y-2"><Label htmlFor="login-to">To</Label><Input
          id="login-to"
          type="date"
          value={dateTo}
          min={dateFrom || undefined}
          onChange={(event) => { setDateTo(event.target.value); resetPage(); }}
        /></div>
      </div>
      <DataTable
        columns={columns}
        rows={rows}
        initialSort={{ key: "time", direction: "desc" }}
        getRowKey={(row) => row.id}
        loading={isLoading}
        error={isError}
        emptyState={<EmptyState title="No login logs" description="No login attempts match these filters." />}
        errorState={<EmptyState title="Could not load login logs" description="Check the API connection and try again." />}
        clientSort={false}
      />
      <div className="flex items-center justify-between text-small text-text-muted">
        <span>{data?.total ?? 0} result{data?.total === 1 ? "" : "s"}</span>
        <div className="flex items-center gap-2">
          <Button type="button" variant="secondary" className="h-9" disabled={page <= 1 || isLoading} onClick={() => setPage((value) => value - 1)}>Previous</Button>
          <span>Page {page} of {totalPages}</span>
          <Button type="button" variant="secondary" className="h-9" disabled={page >= totalPages || isLoading} onClick={() => setPage((value) => value + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
};

type PlatformIngestionRow = IngestionLog & { row_key: string; platform: string; resolved: boolean };

const IngestionTable = () => {
  const [sourceId, setSourceId] = useState(0);
  const [status, setStatus] = useState<IngestionStatus | "all">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailPlatform, setDetailPlatform] = useState<string | null>(null);
  const [detailResolved, setDetailResolved] = useState(false);
  const pageSize = 25;
  const { data, isLoading, isError } = useIngestionLogsQuery({ sourceId: sourceId || undefined, status, dateFrom, dateTo, page, pageSize });
  const { data: sources = [] } = useSourcesQuery();
  const { data: detail } = useIngestionLogQuery(detailId);
  const retryMutation = useRetryIngestionMutation();
  const runs = data?.items ?? [];
  const latestCompletedBySource = runs.reduce<Map<number, number>>((latest, run) => {
    if (run.status === "completed") {
      const timestamp = new Date(run.run_timestamp).getTime();
      latest.set(run.source_id, Math.max(latest.get(run.source_id) ?? 0, timestamp));
    }
    return latest;
  }, new Map());
  const rows: PlatformIngestionRow[] = runs.flatMap((run) => {
    const resolved = run.status === "failed"
      && (latestCompletedBySource.get(run.source_id) ?? 0) > new Date(run.run_timestamp).getTime();
    const platforms = Object.entries(run.platform_breakdown);
    if (!platforms.length) {
      const platform = run.source_name === "CNRS Webhook" ? "CNRS API" : "Not recorded";
      return [{ ...run, row_key: `${run.id}-${platform}`, platform, resolved }];
    }
    return platforms.map(([platform, counts]) => ({ ...run, row_key: `${run.id}-${platform}`, platform: platform.charAt(0).toUpperCase() + platform.slice(1), messages_fetched: counts.fetched, messages_parsed: counts.parsed, messages_flagged: counts.flagged, messages_failed: counts.failed, messages_blocked: counts.blocked, resolved }));
  }).filter((row) => !(
    row.status === "completed"
    && row.messages_fetched > 0
    && row.messages_parsed === 0
  ));
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  const resetPage = () => setPage(1);
  const duration = (seconds: number | null) => seconds === null ? "In progress" : seconds < 1 ? "<1s" : seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const detailCounts = detail && detailPlatform && detail.platform_breakdown[detailPlatform.toLowerCase()]
    ? detail.platform_breakdown[detailPlatform.toLowerCase()]
    : detail
      ? { fetched: detail.messages_fetched, parsed: detail.messages_parsed, flagged: detail.messages_flagged, failed: detail.messages_failed, blocked: detail.messages_blocked }
      : null;
  const ingestionResult = (row: PlatformIngestionRow) => {
    if (row.resolved) return "Recovered by a later run";
    if (row.status === "running") return "Checking for news";
    if (row.status === "failed") return "Run failed";
    if (row.status === "interrupted") return "Stopped by restart";
    if (row.messages_parsed > 0) return `${row.messages_parsed} new saved`;
    if (row.messages_fetched > 0) return "No new recent news";
    return "No records returned";
  };
  const columns: Array<DataTableColumn<PlatformIngestionRow>> = [
    { key: "platform", header: "Platform", render: (row) => <span className="font-semibold text-brand-navy">{row.platform}</span>, sortValue: (row) => row.platform },
    { key: "time", header: "Run date & time", render: (row) => formatDateTime(row.run_timestamp), sortValue: (row) => new Date(row.run_timestamp).getTime() },
    { key: "fetched", header: "Fetched", render: (row) => row.messages_fetched, sortValue: (row) => row.messages_fetched },
    { key: "saved", header: "Saved", render: (row) => row.messages_parsed, sortValue: (row) => row.messages_parsed },
    { key: "result", header: "Result", render: (row) => ingestionResult(row), sortValue: (row) => ingestionResult(row) },
    { key: "duration", header: "Duration", render: (row) => duration(row.duration_seconds), sortValue: (row) => row.duration_seconds },
    { key: "status", header: "Status", render: (row) => <StatusBadge label={row.resolved ? "resolved" : row.status} variant={row.status === "completed" || row.resolved ? "success" : row.status === "failed" ? "danger" : "warning"} />, sortValue: (row) => row.resolved ? "resolved" : row.status },
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-surface-raised p-4 md:grid-cols-4">
        <div className="space-y-2"><Label htmlFor="ingestion-source">Source</Label><select id="ingestion-source" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3" value={sourceId} onChange={(event) => { setSourceId(Number(event.target.value)); resetPage(); }}>
          <option value={0}>All sources</option>
          {sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
        </select></div>
        <div className="space-y-2"><Label htmlFor="ingestion-status">Status</Label><select id="ingestion-status" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3" value={status} onChange={(event) => { setStatus(event.target.value as IngestionStatus | "all"); resetPage(); }}>
          <option value="all">All statuses</option><option value="running">Running</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="interrupted">Interrupted</option>
        </select></div>
        <div className="space-y-2"><Label htmlFor="ingestion-from">From</Label><Input id="ingestion-from" type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => { setDateFrom(event.target.value); resetPage(); }} /></div>
        <div className="space-y-2"><Label htmlFor="ingestion-to">To</Label><Input id="ingestion-to" type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => { setDateTo(event.target.value); resetPage(); }} /></div>
      </div>
      <DataTable columns={columns} rows={rows} initialSort={{ key: "time", direction: "desc" }} clientSort={false} getRowKey={(row) => row.row_key} loading={isLoading} error={isError} minWidth="1120px" emptyState={<EmptyState title="No ingestion logs" description="No ingestion runs match these filters." />} errorState={<EmptyState title="Could not load ingestion logs" description="Check the API connection and try again." />} actions={(row) => <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => { setDetailId(row.id); setDetailPlatform(row.platform); setDetailResolved(row.resolved); }}>Details</Button>{row.status === "failed" && !row.resolved ? <Button type="button" isLoading={retryMutation.isPending && retryMutation.variables === row.id} onClick={() => retryMutation.mutate(row.id)}>Retry</Button> : null}</div>} />
      <div className="flex items-center justify-between text-small text-text-muted"><span>{data?.total ?? 0} results</span><div className="flex items-center gap-2"><Button type="button" variant="secondary" className="h-9" disabled={page <= 1 || isLoading} onClick={() => setPage((value) => value - 1)}>Previous</Button><span>Page {page} of {totalPages}</span><Button type="button" variant="secondary" className="h-9" disabled={page >= totalPages || isLoading} onClick={() => setPage((value) => value + 1)}>Next</Button></div></div>
      {detailId !== null && detail ? (
        <Dialog
          title={`${detailPlatform ?? "Unrecorded platform"} ingestion details`}
          onClose={() => { setDetailId(null); setDetailPlatform(null); setDetailResolved(false); }}
        >
          <p className="mb-5 text-small text-text-muted">Run ID: {detail.id}</p>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Source</dt><dd>{detailPlatform === "CNRS API" ? "CNRS API" : detail.source_name}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Platform</dt><dd>{detailPlatform ?? "Not recorded"}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Status</dt><dd>{detailResolved ? "Resolved" : detail.status}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Started</dt><dd>{detail.started_at ? formatDateTime(detail.started_at) : "Unknown"}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Finished</dt><dd>{detail.finished_at ? formatDateTime(detail.finished_at) : "Running"}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Duration</dt><dd>{duration(detail.duration_seconds)}</dd></div>
            {detail.retry_of_id ? <div><dt className="text-caption font-semibold uppercase text-text-muted">Retry of run</dt><dd>{detail.retry_of_id}</dd></div> : null}
          </dl>
          {detailCounts ? <div className="mt-5 grid grid-cols-2 gap-3 rounded-md border border-border bg-surface p-4 sm:grid-cols-5"><div><p className="text-caption font-semibold uppercase text-text-muted">Fetched</p><p className="mt-1 text-lg font-semibold">{detailCounts.fetched}</p></div><div><p className="text-caption font-semibold uppercase text-text-muted">Saved</p><p className="mt-1 text-lg font-semibold">{detailCounts.parsed}</p></div><div><p className="text-caption font-semibold uppercase text-text-muted">Flagged</p><p className="mt-1 text-lg font-semibold">{detailCounts.flagged}</p></div><div><p className="text-caption font-semibold uppercase text-text-muted">Failed</p><p className="mt-1 text-lg font-semibold">{detailCounts.failed}</p></div><div><p className="text-caption font-semibold uppercase text-text-muted">Blocked</p><p className="mt-1 text-lg font-semibold">{detailCounts.blocked}</p></div></div> : null}
          {detailResolved ? <div className="mt-5 rounded-md border border-border bg-surface p-4"><p className="text-caption font-semibold uppercase text-text-muted">Resolution</p><p className="mt-2 text-small">A later CNRS API run completed successfully. No retry is required.</p></div> : detail.status === "failed" ? <div className="mt-5 rounded-md border border-border bg-surface p-4"><p className="text-caption font-semibold uppercase text-text-muted">Failure reason</p><p className="mt-2 whitespace-pre-wrap text-small">{detail.error_message || "No failure reason was provided."}</p></div> : null}
        </Dialog>
      ) : null}
    </div>
  );
};

const formatWaitingSeconds = (seconds: number | null): string => {
  if (seconds === null) return "—";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
};

const LatencyCohortCard = ({ title, cohort }: { title: string; cohort: PipelineLatencyCohort }) => (
  <div className="rounded-md border border-border bg-surface p-4">
    <p className="text-caption font-semibold uppercase text-text-muted">{title}</p>
    <p className="mt-1 text-caption text-text-muted">{cohort.sample_size} sample{cohort.sample_size === 1 ? "" : "s"}</p>
    <dl className="mt-3 grid grid-cols-3 gap-3">
      {([["p50", cohort.p50_seconds], ["p95", cohort.p95_seconds], ["p99", cohort.p99_seconds]] as const).map(([label, value]) => (
        <div key={label}>
          <dt className="text-caption font-semibold uppercase text-text-muted">{label}</dt>
          <dd className="mt-1 text-lg font-semibold">{formatWaitingSeconds(value)}</dd>
        </div>
      ))}
    </dl>
  </div>
);

export const PipelineHealthPanel = () => {
  const { data, isLoading, isError, isFetching, refetch } = usePipelineHealthQuery();

  const columns: Array<DataTableColumn<PipelineStageQueueDepth>> = [
    { key: "stage", header: "Stage", render: (row) => <span className="font-semibold text-text-primary">{row.stage_name}</span> },
    { key: "depth", header: "Queue depth", render: (row) => <span className={cn(row.queue_depth > 0 ? "font-semibold text-text-primary" : "text-text-muted")}>{row.queue_depth}</span> },
    { key: "oldest", header: "Oldest waiting", render: (row) => formatWaitingSeconds(row.oldest_waiting_seconds) },
  ];

  const cursorGap = data?.cursor_gap;
  const latency = data?.latency;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-small text-text-muted">Read-only snapshot of <code className="text-caption">GET /api/pipeline/health</code>. Refresh manually.</p>
        <Button type="button" variant="secondary" isLoading={isFetching} onClick={() => refetch()}>Refresh</Button>
      </div>

      <DataTable
        columns={columns}
        rows={data?.stages ?? []}
        getRowKey={(row) => row.stage_name}
        loading={isLoading}
        error={isError}
        clientSort={false}
        emptyState={<EmptyState title="No stage data" description="The pipeline health endpoint returned no stages." />}
        errorState={<EmptyState title="Could not load pipeline health" description="Check the API connection and that you are signed in as a super admin." />}
      />

      {cursorGap ? (
        <div className={cn("rounded-lg border p-4", cursorGap.unhealthy ? "border-danger bg-danger/5" : "border-border bg-surface-raised")}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-small font-semibold text-text-primary">Live-sweep cursor gap</h3>
            <StatusBadge label={cursorGap.unhealthy ? "Unhealthy" : "Healthy"} variant={cursorGap.unhealthy ? "danger" : "success"} />
          </div>
          <dl className="grid gap-4 sm:grid-cols-4">
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Sweep</dt><dd className="mt-1 break-all">{cursorGap.sweep_name}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Last processed id</dt><dd className="mt-1">{cursorGap.last_processed_id}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Max raw_message id</dt><dd className="mt-1">{cursorGap.max_raw_message_id ?? "—"}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Gap</dt><dd className={cn("mt-1 font-semibold", cursorGap.unhealthy ? "text-danger" : "text-text-primary")}>{cursorGap.gap}</dd></div>
          </dl>
        </div>
      ) : null}

      {latency ? (
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <h3 className="mb-1 text-small font-semibold text-text-primary">Latency percentiles</h3>
          <p className="mb-3 text-caption text-text-muted">Rolling {latency.window_hours}h window · received_at → done · no SLO target</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <LatencyCohortCard title="Materialized (received → materialized_at)" cohort={latency.materialized} />
            <LatencyCohortCard title="Terminal non-materialized (received → matched_at)" cohort={latency.terminal_non_materialized} />
          </div>
        </div>
      ) : null}
    </div>
  );
};

export const LogsPage = () => {
  const { logType = "audit" } = useParams();
  const location = useLocation();
  const isSuperAdmin = location.pathname.startsWith("/superadmin/");
  const logsBasePath = isSuperAdmin ? "/superadmin/logs" : "/admin/logs";
  const visibleTabs = logTabs;
  const activeTab = visibleTabs.find((tab) => tab.value === logType);

  if (!activeTab) {
    return <Navigate to={`${logsBasePath}/audit`} replace />;
  }

  return (
    <div className="space-y-5">
      <div className="border-b border-border">
        <nav className="-mb-px flex gap-2" aria-label="Log categories">
          {visibleTabs.map((tab) => (
            <NavLink
              key={tab.value}
              to={`${logsBasePath}/${tab.value}`}
              className={({ isActive }) =>
                cn(
                  "border-b-2 px-3 py-2 text-small font-semibold transition-colors duration-150 ease-out",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
                  isActive ? "border-accent text-accent" : "border-transparent text-text-muted hover:border-border-strong hover:text-text-primary",
                )
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
      </div>
      {logType === "audit" ? <AuditTable /> : logType === "login" ? <LoginTable /> : logType === "pipeline" ? <PipelineHealthPanel /> : <IngestionTable />}
    </div>
  );
};
