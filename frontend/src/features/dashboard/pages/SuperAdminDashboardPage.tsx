import { Link } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Card } from "../../../components/ui";
import { formatRelativeTime } from "../../../lib/formatters";
import { mockAuditLogs, mockLoginLogs } from "../../../mocks/mockLogs";
import { mockSources } from "../../../mocks/mockSources";
import { useAccounts } from "../../accounts/hooks";

const Metric = ({ label, value, detail, alert = false }: { label: string; value: number; detail: string; alert?: boolean }) => (
  <Card className="p-5">
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-caption font-semibold uppercase tracking-wide text-text-muted">{label}</p>
        <p className="mt-2 text-h2 font-semibold text-text-primary">{value}</p>
      </div>
      <span className={`mt-1 h-2.5 w-2.5 rounded-full ${alert ? "bg-danger" : "bg-success"}`} aria-hidden="true" />
    </div>
    <p className="mt-3 text-small text-text-muted">{detail}</p>
  </Card>
);

const ActionLink = ({ to, title, description }: { to: string; title: string; description: string }) => (
  <Link to={to} className="block rounded-lg border border-border bg-surface-raised p-5 shadow-raised transition-colors hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
    <p className="font-semibold text-text-primary">{title}</p>
    <p className="mt-2 text-small text-text-muted">{description}</p>
    <p className="mt-4 text-small font-semibold text-accent">Open {title.toLowerCase()} →</p>
  </Link>
);

export const SuperAdminDashboardPage = () => {
  const { data: accounts = [] } = useAccounts();
  const activeUsers = accounts.filter((user) => user.is_active);
  const superAdministrators = accounts.filter((user) => user.role.name === "super_admin");
  const sourceIssues = mockSources.filter((source) => source.health !== "healthy");
  const failedLogins = mockLoginLogs.filter((entry) => !entry.success);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border bg-surface-raised p-5 sm:p-6">
        <p className="text-caption font-semibold uppercase tracking-wide text-accent">System administration</p>
        <h2 className="mt-2 text-h3 font-semibold text-text-primary">Super Admin control center</h2>
        <p className="mt-2 max-w-2xl text-small text-text-muted">Manage administrator accounts, monitor ingestion sources, and review security and audit activity.</p>
      </section>

      <section aria-label="System metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Active accounts" value={activeUsers.length} detail={`${accounts.length - activeUsers.length} inactive accounts`} />
        <Metric label="Administrators" value={superAdministrators.length} detail="Super administrator accounts" />
        <Metric label="Source issues" value={sourceIssues.length} detail="Sources paused or in error" alert={sourceIssues.length > 0} />
        <Metric label="Failed logins" value={failedLogins.length} detail="Recent unsuccessful attempts" alert={failedLogins.length > 0} />
      </section>

      <section>
        <h2 className="mb-4 text-h4 font-semibold text-text-primary">Administration</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <ActionLink to="/superadmin/accounts" title="Accounts" description="Create, update, activate, or deactivate administrator access." />
          <ActionLink to="/superadmin/sources" title="Sources" description="Monitor source health and control ingestion availability." />
          <ActionLink to="/superadmin/logs/audit" title="Audit logs" description="Review account, source, login, and ingestion activity." />
        </div>
      </section>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-h4 font-semibold text-text-primary">Recent audit activity</h2>
            <p className="mt-1 text-small text-text-muted">Latest privileged system changes</p>
          </div>
          <Link to="/superadmin/logs/audit" className="text-small font-semibold text-accent hover:text-accent-hover">View all</Link>
        </div>
        <div className="divide-y divide-border">
          {mockAuditLogs.map((entry) => (
            <div key={entry.id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-small font-semibold text-text-primary">{entry.action}</p>
                  <StatusBadge label={entry.target} variant="neutral" />
                </div>
                <p className="mt-1 text-caption text-text-muted">Performed by {entry.performed_by}</p>
              </div>
              <span className="text-caption text-text-muted">{formatRelativeTime(entry.timestamp)}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
