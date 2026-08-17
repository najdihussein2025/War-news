import { Link, useLocation, useParams } from "react-router-dom";
import { EmptyState } from "../../../components/ui";
import { roleBaseFromPath } from "../../../lib/rolePath";

export const IncidentDetailPage = () => {
  const { incidentId } = useParams();
  const roleBase = roleBaseFromPath(useLocation().pathname);
  return <section className="rounded-lg border border-border bg-surface-raised"><EmptyState title="Incident details unavailable" description={`No authenticated detail endpoint exists for incident ${incidentId ?? "this record"}. Sample edit, archive, review, and comparison actions were removed.`} /><div className="pb-8 text-center"><Link className="font-semibold text-accent hover:text-accent-hover" to={`${roleBase}/incidents`}>Back to incidents</Link></div></section>;
};
