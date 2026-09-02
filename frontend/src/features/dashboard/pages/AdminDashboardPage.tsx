import { Link } from "react-router-dom";
import { Card, EmptyState } from "../../../components/ui";
import { formatDate } from "../../../lib/formatters";
import { useIncidentsQuery } from "../../news/hooks";

const DashboardLink = ({ label, detail, action, to }: { label: string; detail: string; action: string; to: string }) => (
  <Link to={to} className="block rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
  <Card className="h-full p-5 transition-colors hover:border-brand-navy hover:bg-brand-sky/20">
    <p className="text-h4 font-semibold text-brand-navy">{label}</p>
    <p className="mt-3 text-small text-text-muted">{detail}</p>
    <p className="mt-5 text-small font-semibold text-brand-green">{action} →</p>
  </Card>
  </Link>
);

export const AdminDashboardPage = () => {
  const incidents = useIncidentsQuery({ limit: 5 }, false);

  return <div className="space-y-6">
    <section className="rounded-lg border border-border bg-surface-raised p-5 sm:p-6"><p className="text-caption font-semibold uppercase tracking-wide text-accent">Operations overview</p><h2 className="mt-2 text-h3 font-semibold text-text-primary">Incident operations</h2></section>
    <section aria-label="Admin quick access" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <DashboardLink label="Incidents" detail="Review, filter, create, and update incident records." action="Manage incidents" to="/admin/incidents" />
      <DashboardLink label="Air Violations" detail="Review, filter, create, and export air-violation records." action="Review air violations" to="/admin/air-violations" />
      <DashboardLink label="Sources" detail="Monitor source activity, news volume, and reporting status." action="Monitor sources" to="/admin/sources" />
      <DashboardLink label="Settings" detail="Update your profile, password, and account preferences." action="Update settings" to="/admin/settings" />
    </section>
    <section><div className="mb-4 flex items-center justify-between gap-4"><h2 className="text-h4 font-semibold text-text-primary">Recent incidents</h2><Link className="text-small font-semibold text-accent hover:underline" to="/admin/incidents">View all incidents →</Link></div>
      {!incidents.isLoading && (incidents.data?.items.length ?? 0) === 0 ? <Card><EmptyState title="No incidents recorded" description="New verified incident records will appear here." /></Card> : <Card className="divide-y divide-border overflow-hidden p-0">
        {(incidents.data?.items ?? []).map((incident) => <Link className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-surface-muted sm:flex-row sm:items-center sm:justify-between" key={incident.id} to={`/admin/incidents/${incident.id}`}><div className="min-w-0"><p className="truncate font-semibold text-text-primary">{incident.condition ?? "No condition"}</p><p className="mt-1 truncate text-small text-text-muted">{incident.village ?? "Location not specified"} · {incident.source ?? "No source"}</p></div><time className="whitespace-nowrap text-caption text-text-muted" dateTime={incident.event_date}>{formatDate(incident.event_date)}</time></Link>)}
        {incidents.isLoading ? <p className="px-5 py-6 text-center text-small text-text-muted">Loading recent incidents…</p> : null}
      </Card>}
    </section>
  </div>;
};
