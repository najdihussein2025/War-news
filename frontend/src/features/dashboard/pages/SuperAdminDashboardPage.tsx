import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Card, EmptyState } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { useAirViolationsQuery } from "../../airViolations/hooks";
import { useAuditLogsQuery, useIngestionLogsQuery, useLoginLogsQuery } from "../../logs/hooks";
import { useIncidentsQuery } from "../../news/hooks";
import { useContentSourcesQuery } from "../../sources/hooks";
import { refreshDashboardQueries } from "../refreshQueries";

const Metric = ({ label, value, detail, to, alert = false, loading = false }: { label: string; value: number; detail: string; to: string; alert?: boolean; loading?: boolean }) => (
  <Link to={to} className="block rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><Card className="h-full p-5 transition-colors hover:border-brand-navy hover:bg-brand-sky/20"><div className="flex items-start justify-between gap-4"><div><p className="text-caption font-semibold uppercase tracking-wide text-brand-navy">{label}</p>{loading ? <div className="mt-3 h-10 w-20 animate-pulse rounded bg-surface-muted" /> : <p className="mt-2 text-h2 font-semibold tabular-nums text-brand-navy">{value}</p>}</div><span className={`mt-1 h-2.5 w-2.5 rounded-full ${alert ? "bg-danger" : "bg-success"}`} aria-hidden="true" /></div><p className="mt-3 text-small text-text-muted">{detail}</p></Card></Link>
);

const ActionLink = ({ to, title, description }: { to: string; title: string; description: string }) => (
  <Link to={to} className="block rounded-lg border border-border bg-surface-raised p-5 shadow-raised transition-colors hover:border-brand-navy hover:bg-brand-sky/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><p className="font-semibold text-brand-navy">{title}</p><p className="mt-2 text-small text-text-muted">{description}</p><p className="mt-4 text-small font-semibold text-brand-green">Open {title.toLowerCase()} →</p></Link>
);

const yesterday = () => getBeirutDate(-1);
const today = () => getBeirutDate();
const friendlyAuditAction = (action: string) => ({
  "content_source.blocked": "Source paused",
  "content_source.unblocked": "Source resumed",
  "system.audit_enabled": "Audit logging enabled",
  "user.created": "Account created",
  "user.updated": "Account updated",
  "user.deleted": "Account deleted",
}[action] ?? action.replace(/[._]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()));

export const SuperAdminDashboardPage = () => {
  const [lastUpdated, setLastUpdated] = useState(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState<"idle" | "success" | "error">("idle");
  const contentSources = useContentSourcesQuery();
  const incidents = useIncidentsQuery({ limit: 1, offset: 0 });
  const incidentsToday = useIncidentsQuery({ limit: 1, offset: 0, eventDateFrom: today() });
  const airViolations = useAirViolationsQuery({ limit: 1, offset: 0 });
  const airViolationsToday = useAirViolationsQuery({ limit: 1, offset: 0, eventDateFrom: today() });
  const failedLogins = useLoginLogsQuery({ result: "failure", dateFrom: yesterday(), page: 1, pageSize: 1 });
  const ingestion = useIngestionLogsQuery({ status: "all", dateFrom: today(), page: 1, pageSize: 100 });
  const auditLogs = useAuditLogsQuery({ page: 1, pageSize: 5 });
  const ingestionRows = ingestion.data?.items ?? [];
  const newsToday = ingestionRows.reduce((total, row) => total + row.messages_parsed, 0);
  const failedIngestion = ingestionRows.filter((row) => row.status === "failed").length;
  const runningIngestion = ingestionRows.filter((row) => row.status === "running").length;

  const refresh = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setRefreshStatus("idle");
    try {
      const hasError = await refreshDashboardQueries([
        contentSources.refetch,
        incidents.refetch,
        incidentsToday.refetch,
        airViolations.refetch,
        airViolationsToday.refetch,
        failedLogins.refetch,
        ingestion.refetch,
        auditLogs.refetch,
      ]);
      if (hasError) {
        setRefreshStatus("error");
      } else {
        setLastUpdated(new Date());
        setRefreshStatus("success");
      }
    } finally {
      setIsRefreshing(false);
    }
  };

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      void refreshRef.current();
    }, 30_000);
    return () => window.clearInterval(intervalId);
  }, []);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border border-l-4 border-l-brand-gold bg-gradient-to-r from-brand-gold-soft/60 to-white p-5 sm:p-6">
        <div><p className="text-caption font-semibold uppercase tracking-wide text-accent">System administration</p><h2 className="mt-2 text-h3 font-semibold text-text-primary">System overview</h2><p className="mt-2 max-w-2xl text-small text-text-muted">Live operational and security information from the backend. Updates automatically every 30 seconds.</p><p className={`mt-2 text-caption ${refreshStatus === "error" ? "text-danger" : refreshStatus === "success" ? "text-success" : "text-text-muted"}`} role="status" aria-live="polite">{refreshStatus === "error" ? "Some dashboard data could not be refreshed. The system will try again automatically." : refreshStatus === "success" ? `Automatically updated at ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : `Last updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`}</p></div>
      </section>

      <section aria-label="System metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label="Content sources" value={contentSources.data?.length ?? 0} detail="Upstream news accounts" to="/superadmin/sources" loading={contentSources.isLoading} />
        <Metric label="News received today" value={newsToday} detail="Parsed through ingestion today" to="/superadmin/logs/ingestion" loading={ingestion.isLoading} />
        <Metric label="Incidents" value={incidents.data?.total ?? 0} detail={`+${incidentsToday.data?.total ?? 0} recorded today`} to="/superadmin/incidents" loading={incidents.isLoading || incidentsToday.isLoading} />
        <Metric label="Air violations" value={airViolations.data?.total ?? 0} detail={`+${airViolationsToday.data?.total ?? 0} recorded today`} to="/superadmin/air-violations" loading={airViolations.isLoading || airViolationsToday.isLoading} />
        <Metric label="Failed ingestions today" value={failedIngestion} detail={`${runningIngestion} currently running`} to="/superadmin/logs/ingestion" alert={failedIngestion > 0} loading={ingestion.isLoading} />
        <Metric label="Failed logins (24h)" value={failedLogins.data?.total ?? 0} detail="Open filtered security log" to={`/superadmin/logs/login?result=failure&date_from=${yesterday()}`} alert={(failedLogins.data?.total ?? 0) >= 5} loading={failedLogins.isLoading} />
      </section>

      <section><h2 className="mb-4 text-h4 font-semibold text-text-primary">Quick access</h2><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><ActionLink to="/superadmin/incidents" title="Incidents" description="Review incident reports." /><ActionLink to="/superadmin/air-violations" title="Air Violations" description="Manage air activity records." /><ActionLink to="/superadmin/sources" title="Sources" description="Monitor upstream accounts." /><ActionLink to="/superadmin/accounts" title="Accounts" description="Manage administrator access." /><ActionLink to="/superadmin/logs/audit" title="Audit Logs" description="Review privileged changes." /></div></section>

      <section>
        <div className="mb-4 flex items-center justify-between gap-4"><h2 className="text-h4 font-semibold text-text-primary">Recent audit activity</h2><Link className="text-small font-semibold text-accent hover:underline" to="/superadmin/logs/audit">View all audit logs →</Link></div>
        {auditLogs.isError ? (
          <Card><EmptyState title="Could not load audit activity" description="Refresh the dashboard or open Audit Logs to try again." /></Card>
        ) : !auditLogs.isLoading && (auditLogs.data?.items.length ?? 0) === 0 ? (
          <Card><EmptyState title="No audit activity yet" description="Privileged account and configuration changes will appear here." /></Card>
        ) : (
          <Card className="divide-y divide-border overflow-hidden p-0">
            {(auditLogs.data?.items ?? []).map((entry) => <div className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between" key={entry.id}><div><p className="font-semibold text-text-primary">{friendlyAuditAction(entry.action)}</p><p className="mt-1 text-small text-text-muted">{entry.performed_by} · {entry.target_type.replace(/_/g, " ")}: {entry.target}</p></div><time className="whitespace-nowrap text-caption text-text-muted" dateTime={entry.timestamp}>{formatDateTime(entry.timestamp)}</time></div>)}
            {auditLogs.isLoading ? <p className="px-5 py-6 text-center text-small text-text-muted">Loading audit activity…</p> : null}
          </Card>
        )}
      </section>
    </div>
  );
};
