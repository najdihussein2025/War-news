import { Link } from "react-router-dom";
import { Card, EmptyState } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { useAirViolationsQuery } from "../../airViolations/hooks";
import { useAuditLogsQuery, useIngestionLogsQuery, useLoginLogsQuery } from "../../logs/hooks";
import { useIncidentsQuery } from "../../news/hooks";
import { useContentSourcesQuery } from "../../sources/hooks";

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
  const contentSources = useContentSourcesQuery();
  const incidents = useIncidentsQuery({ limit: 1, offset: 0 }, false);
  const incidentsToday = useIncidentsQuery({ limit: 1, offset: 0, eventDateFrom: today() }, false);
  const airViolations = useAirViolationsQuery({ limit: 1, offset: 0 }, false);
  const airViolationsToday = useAirViolationsQuery({ limit: 1, offset: 0, eventDateFrom: today() }, false);
  const failedLogins = useLoginLogsQuery({ result: "failure", dateFrom: yesterday(), page: 1, pageSize: 1 });
  const ingestion = useIngestionLogsQuery({ status: "all", dateFrom: today(), page: 1, pageSize: 100 });
  const auditLogs = useAuditLogsQuery({ page: 1, pageSize: 5 });
  const ingestionRows = ingestion.data?.items ?? [];
  const newsToday = ingestionRows.reduce((total, row) => total + row.messages_parsed, 0);
  const latestCompletedBySource = ingestionRows.reduce<Map<number, number>>((latest, row) => {
    if (row.status === "completed") {
      const timestamp = new Date(row.run_timestamp).getTime();
      latest.set(row.source_id, Math.max(latest.get(row.source_id) ?? 0, timestamp));
    }
    return latest;
  }, new Map());
  const failedIngestion = ingestionRows.filter((row) =>
    row.status === "failed"
    && new Date(row.run_timestamp).getTime() > (latestCompletedBySource.get(row.source_id) ?? 0)
  ).length;
  const runningIngestion = ingestionRows.filter((row) => row.status === "running").length;
  const reportingSources = (contentSources.data ?? []).filter(
    (source) => Date.now() - new Date(source.last_seen).getTime() <= 24 * 60 * 60 * 1000,
  ).length;
  const staleSources = Math.max(0, (contentSources.data?.length ?? 0) - reportingSources);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border border-l-4 border-l-brand-gold bg-gradient-to-r from-brand-gold-soft/60 to-white p-5 sm:p-6">
        <div><p className="text-caption font-semibold uppercase tracking-wide text-accent">System administration</p><h2 className="mt-2 text-h3 font-semibold text-text-primary">System overview</h2></div>
      </section>

      <section aria-label="System metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label="Content sources" value={contentSources.data?.length ?? 0} detail="Upstream news accounts" to="/superadmin/sources" loading={contentSources.isLoading} />
        <Metric label="News received today" value={newsToday} detail="Parsed through ingestion today" to="/superadmin/logs/ingestion" loading={ingestion.isLoading} />
        <Metric label="Incidents" value={incidents.data?.total ?? 0} detail={`+${incidentsToday.data?.total ?? 0} recorded today`} to="/superadmin/incidents" loading={incidents.isLoading || incidentsToday.isLoading} />
        <Metric label="Air violations" value={airViolations.data?.total ?? 0} detail={`+${airViolationsToday.data?.total ?? 0} recorded today`} to="/superadmin/air-violations" loading={airViolations.isLoading || airViolationsToday.isLoading} />
        <Metric label="Sources not reporting (24h)" value={staleSources} detail={`${reportingSources} reporting now · ${failedIngestion} unresolved failure${failedIngestion === 1 ? "" : "s"}${runningIngestion > 0 ? ` · ${runningIngestion} running` : ""}`} to="/superadmin/sources" alert={staleSources > 0 || failedIngestion > 0} loading={contentSources.isLoading || ingestion.isLoading} />
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
