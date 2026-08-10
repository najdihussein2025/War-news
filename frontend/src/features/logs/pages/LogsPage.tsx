import { useState } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, EmptyState, type DataTableColumn } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { formatDateTime } from "../../../lib/formatters";
import { useAuditLogs, useIngestionLogs, useLoginLogs } from "../../../mocks/useLogs";
import type { MockAuditLog, MockIngestionLog, MockLoginLog } from "../../../mocks/mockLogs";

const logTabs = [
  { label: "Audit", value: "audit" },
  { label: "Login", value: "login" },
  { label: "Ingestion", value: "ingestion" },
];

const AuditTable = () => {
  const { data, isLoading, isError } = useAuditLogs();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const columns: Array<DataTableColumn<MockAuditLog>> = [
    { key: "action", header: "Action", render: (row) => <span className="font-semibold text-text-primary">{row.action}</span>, sortValue: (row) => row.action },
    { key: "by", header: "Performed by", render: (row) => row.performed_by, sortValue: (row) => row.performed_by },
    { key: "target", header: "Target", render: (row) => row.target, sortValue: (row) => row.target },
    { key: "time", header: "Timestamp", render: (row) => formatDateTime(row.timestamp), sortValue: (row) => new Date(row.timestamp).getTime() },
    {
      key: "diff",
      header: "Diff",
      render: (row) => expandedId === row.id ? (
        <pre className="max-w-md overflow-x-auto rounded-md border border-border bg-surface p-3 text-caption text-text-muted">{JSON.stringify({ old_values: row.old_values, new_values: row.new_values }, null, 2)}</pre>
      ) : <span className="text-text-muted">Collapsed</span>,
    },
  ];
  return <DataTable columns={columns} rows={data} getRowKey={(row) => row.id} loading={isLoading} error={isError} emptyState={<EmptyState title="No audit logs" description="Audit events will appear here." />} errorState={<EmptyState title="Could not load audit logs" description="The mocked error state is ready." />} actions={(row) => <Button type="button" variant="secondary" className="h-9" onClick={() => setExpandedId((id) => id === row.id ? null : row.id)}>{expandedId === row.id ? "Collapse" : "Expand"}</Button>} />;
};

const LoginTable = () => {
  const { data, isLoading, isError } = useLoginLogs();
  const columns: Array<DataTableColumn<MockLoginLog>> = [
    { key: "username", header: "Username", render: (row) => <span className={cn("font-semibold", row.success ? "text-text-primary" : "text-danger")}>{row.username}</span>, sortValue: (row) => row.username },
    { key: "time", header: "Timestamp", render: (row) => formatDateTime(row.timestamp), sortValue: (row) => new Date(row.timestamp).getTime() },
    { key: "result", header: "Result", render: (row) => <StatusBadge label={row.success ? "Success" : "Failure"} variant={row.success ? "success" : "danger"} />, sortValue: (row) => row.success ? 1 : 0 },
    { key: "ip", header: "IP", render: (row) => row.ip, sortValue: (row) => row.ip },
  ];
  return <DataTable columns={columns} rows={data} getRowKey={(row) => row.id} loading={isLoading} error={isError} emptyState={<EmptyState title="No login logs" description="Login activity will appear here." />} errorState={<EmptyState title="Could not load login logs" description="The mocked error state is ready." />} />;
};

const IngestionTable = () => {
  const { data, isLoading, isError } = useIngestionLogs();
  const columns: Array<DataTableColumn<MockIngestionLog>> = [
    { key: "source", header: "Source", render: (row) => <span className="font-semibold text-text-primary">{row.source_name}</span>, sortValue: (row) => row.source_name },
    { key: "time", header: "Run timestamp", render: (row) => formatDateTime(row.run_timestamp), sortValue: (row) => new Date(row.run_timestamp).getTime() },
    { key: "stats", header: "Stats", render: (row) => <span className="text-text-muted">{row.messages_fetched} fetched / {row.parsed} parsed / {row.flagged} flagged / {row.failed} failed</span> },
    { key: "status", header: "Status", render: (row) => <StatusBadge label={row.status} variant={row.status === "completed" ? "success" : row.status === "failed" ? "danger" : "warning"} />, sortValue: (row) => row.status },
  ];
  return <DataTable columns={columns} rows={data} getRowKey={(row) => row.id} loading={isLoading} error={isError} emptyState={<EmptyState title="No ingestion logs" description="Ingestion runs will appear here." />} errorState={<EmptyState title="Could not load ingestion logs" description="The mocked error state is ready." />} />;
};

export const LogsPage = () => {
  const { logType = "audit" } = useParams();
  const activeTab = logTabs.find((tab) => tab.value === logType);

  if (!activeTab) {
    return <Navigate to="/logs/audit" replace />;
  }

  return (
    <div className="space-y-5">
      <div className="border-b border-border">
        <nav className="-mb-px flex gap-2" aria-label="Log categories">
          {logTabs.map((tab) => (
            <NavLink
              key={tab.value}
              to={`/logs/${tab.value}`}
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
      {logType === "audit" ? <AuditTable /> : logType === "login" ? <LoginTable /> : <IngestionTable />}
    </div>
  );
};
