import { Link } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Card } from "../../../components/ui";
import { formatRelativeTime } from "../../../lib/formatters";
import { mockIncidents } from "../../../mocks/mockIncidents";

const MetricCard = ({ label, value, detail, tone = "default" }: { label: string; value: number; detail: string; tone?: "default" | "warning" | "danger" }) => (
  <Card className="p-5">
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-caption font-semibold uppercase tracking-wide text-text-muted">{label}</p>
        <p className="mt-2 text-h2 font-semibold text-text-primary">{value}</p>
      </div>
      <span className={`mt-1 h-2.5 w-2.5 rounded-full ${tone === "danger" ? "bg-danger" : tone === "warning" ? "bg-warning" : "bg-success"}`} aria-hidden="true" />
    </div>
    <p className="mt-3 text-small text-text-muted">{detail}</p>
  </Card>
);

export const AdminDashboardPage = () => {
  const needsVerification = mockIncidents.filter((item) => !item.matched);
  const possibleDuplicates = mockIncidents.filter((item) => item.duplicate_flag === "possible");
  const manualRecords = mockIncidents.filter((item) => item.source === "Manual");
  const recentIncidents = [...mockIncidents]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border bg-surface-raised p-5 sm:flex sm:items-center sm:justify-between sm:gap-6 sm:p-6">
        <div>
          <p className="text-caption font-semibold uppercase tracking-wide text-accent">Operations overview</p>
          <h2 className="mt-2 text-h3 font-semibold text-text-primary">Review today’s incident feed</h2>
          <p className="mt-2 max-w-2xl text-small text-text-muted">Monitor published records and resolve data-quality flags. Accounts, sources, and audit controls remain restricted to Super Admins.</p>
        </div>
        <Link to="/admin/incidents?flagged=1" className="mt-5 inline-flex h-11 w-full shrink-0 items-center justify-center rounded-md bg-button-primary-bg px-4 text-small font-semibold text-button-primary-text transition-colors hover:bg-button-primary-bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring sm:mt-0 sm:w-auto">Review flagged records</Link>
      </section>

      <section aria-label="Operational metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Total records" value={mockIncidents.length} detail="Incidents currently in the system" />
        <MetricCard label="Needs verification" value={needsVerification.length} detail="Missing a confirmed location match" tone={needsVerification.length ? "warning" : "default"} />
        <MetricCard label="Possible duplicates" value={possibleDuplicates.length} detail="Waiting for an admin review" tone={possibleDuplicates.length ? "warning" : "default"} />
        <MetricCard label="Manual records" value={manualRecords.length} detail="Records entered by an administrator" />
      </section>

      <div>
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h2 className="text-h4 font-semibold text-text-primary">Recent incidents</h2>
              <p className="mt-1 text-small text-text-muted">Latest records added to the feed</p>
            </div>
            <Link to="/admin/incidents" className="text-small font-semibold text-accent hover:text-accent-hover">View all</Link>
          </div>
          <div className="divide-y divide-border">
            {recentIncidents.map((incident) => (
              <Link key={incident.id} to={`/admin/incidents/${incident.id}`} className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus-ring">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold text-text-primary">{incident.village}</p>
                    {!incident.matched ? <StatusBadge label="Verify" variant="warning" /> : null}
                    {incident.duplicate_flag === "possible" ? <StatusBadge label="Possible duplicate" variant="warning" /> : null}
                  </div>
                  <p className="mt-1 truncate text-small text-text-muted">{incident.condition} · {incident.source}</p>
                </div>
                <span className="shrink-0 text-caption text-text-muted">{formatRelativeTime(incident.created_at)}</span>
              </Link>
            ))}
          </div>
        </Card>

      </div>
    </div>
  );
};
