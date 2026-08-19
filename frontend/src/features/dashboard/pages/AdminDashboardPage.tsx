import { Link } from "react-router-dom";
import { Card, EmptyState } from "../../../components/ui";
import { formatDate } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { useIncidentsQuery } from "../../news/hooks";

const Metric = ({ label, value, detail, alert = false, loading = false }: { label: string; value: number; detail: string; alert?: boolean; loading?: boolean }) => (
  <Card className="h-full p-5">
    <div className="flex items-start justify-between gap-4"><div><p className="text-caption font-semibold uppercase tracking-wide text-text-muted">{label}</p>{loading ? <div className="mt-3 h-10 w-20 animate-pulse rounded bg-surface-muted" /> : <p className="mt-2 text-h2 font-semibold tabular-nums text-text-primary">{value}</p>}</div><span className={`mt-1 h-2.5 w-2.5 rounded-full ${alert ? "bg-danger" : "bg-success"}`} aria-hidden="true" /></div>
    <p className="mt-3 text-small text-text-muted">{detail}</p>
  </Card>
);

export const AdminDashboardPage = () => {
  const incidents = useIncidentsQuery({ limit: 5, offset: 0 });
  const incidentsToday = useIncidentsQuery({ limit: 1, offset: 0, eventDateFrom: getBeirutDate() });
  const needsVerification = useIncidentsQuery({ limit: 1, offset: 0, verificationStatus: "needs_verification" });
  const possibleDuplicates = useIncidentsQuery({ limit: 1, offset: 0, duplicateOnly: true });
  const hasError = incidents.isError || incidentsToday.isError || needsVerification.isError || possibleDuplicates.isError;

  return <div className="space-y-6">
    <section className="rounded-lg border border-border bg-surface-raised p-5 sm:p-6"><p className="text-caption font-semibold uppercase tracking-wide text-accent">Operations overview</p><h2 className="mt-2 text-h3 font-semibold text-text-primary">Incident operations</h2><p className="mt-2 max-w-2xl text-small text-text-muted">Live verified totals from the incident database. Data refreshes automatically.</p></section>
    {hasError ? <Card><EmptyState title="Could not load incident metrics" description="Check the API connection, then refresh the dashboard." /></Card> : <section aria-label="Incident metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Total incidents" value={incidents.data?.total ?? 0} detail="All recorded incidents" loading={incidents.isLoading} />
      <Metric label="Recorded today" value={incidentsToday.data?.total ?? 0} detail="Based on Beirut date" loading={incidentsToday.isLoading} />
      <Metric label="Needs verification" value={needsVerification.data?.total ?? 0} detail="Records awaiting review" alert={(needsVerification.data?.total ?? 0) > 0} loading={needsVerification.isLoading} />
      <Metric label="Possible duplicates" value={possibleDuplicates.data?.total ?? 0} detail="Records requiring comparison" alert={(possibleDuplicates.data?.total ?? 0) > 0} loading={possibleDuplicates.isLoading} />
    </section>}
    <section><div className="mb-4 flex items-center justify-between gap-4"><h2 className="text-h4 font-semibold text-text-primary">Recent incidents</h2><Link className="text-small font-semibold text-accent hover:underline" to="/admin/incidents">View all incidents →</Link></div>
      {!incidents.isLoading && (incidents.data?.items.length ?? 0) === 0 ? <Card><EmptyState title="No incidents recorded" description="New verified incident records will appear here." /></Card> : <Card className="divide-y divide-border overflow-hidden p-0">
        {(incidents.data?.items ?? []).map((incident) => <Link className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-surface-muted sm:flex-row sm:items-center sm:justify-between" key={incident.id} to={`/admin/incidents/${incident.id}`}><div className="min-w-0"><p className="truncate font-semibold text-text-primary">{incident.condition}</p><p className="mt-1 truncate text-small text-text-muted">{incident.village ?? "Location not specified"} · {incident.source}</p></div><time className="whitespace-nowrap text-caption text-text-muted" dateTime={incident.event_date}>{formatDate(incident.event_date)}</time></Link>)}
        {incidents.isLoading ? <p className="px-5 py-6 text-center text-small text-text-muted">Loading recent incidents…</p> : null}
      </Card>}
    </section>
  </div>;
};
