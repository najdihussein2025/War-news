import { isAxiosError } from "axios";
import { Link, useLocation, useParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { EmptyState } from "../../../components/ui";
import { formatDate, formatRelativeTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { useIncidentQuery } from "../hooks";
import type {
  CasualtyDemographics,
  IncidentDetail,
  IncidentSource,
} from "../types";

const sourceVariant = (source: IncidentSource) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

const casualtyFields: Array<{
  key: keyof CasualtyDemographics;
  label: string;
}> = [
  { key: "male_d", label: "Male deaths" },
  { key: "male_i", label: "Male injuries" },
  { key: "female_d", label: "Female deaths" },
  { key: "female_i", label: "Female injuries" },
  { key: "children_d", label: "Children deaths" },
  { key: "children_i", label: "Children injuries" },
];

const emptyCategories: Array<{
  key: keyof IncidentDetail;
  label: string;
}> = [
  { key: "lebanese_army", label: "Lebanese Army (LA)" },
  { key: "unifil", label: "UNIFIL" },
  { key: "municipality", label: "Municipality" },
  { key: "school_university", label: "School / University" },
  { key: "religious_cultural", label: "Religious & cultural" },
  { key: "hospital", label: "Hospital" },
  { key: "health_center", label: "Health Center" },
  {
    key: "emergency_civil_defense",
    label: "Emergency / Civil Defense",
  },
  { key: "press", label: "Press" },
  { key: "government_building", label: "Government building" },
  { key: "road_bridge", label: "Road / Bridge" },
  { key: "vehicles", label: "Vehicles" },
  { key: "crossings_other", label: "Crossings & other" },
  { key: "warning_classification", label: "Warning & classification" },
];

const BackLink = ({ to }: { to: string }) => (
  <Link className="font-semibold text-accent hover:text-accent-hover" to={to}>
    Back to incidents
  </Link>
);

export const IncidentDetailPage = () => {
  const { incidentId } = useParams();
  const roleBase = roleBaseFromPath(useLocation().pathname);
  const incidentsPath = `${roleBase}/incidents`;
  const { data: incident, isLoading, error } = useIncidentQuery(incidentId);

  if (isLoading) {
    return (
      <section className="rounded-lg border border-border bg-surface-raised">
        <EmptyState
          title="Loading incident"
          description="Retrieving the incident record."
        />
      </section>
    );
  }

  if (!incident) {
    const notFound =
      !incidentId || (isAxiosError(error) && error.response?.status === 404);
    return (
      <section className="rounded-lg border border-border bg-surface-raised">
        <EmptyState
          title={notFound ? "Incident not found" : "Could not load incident"}
          description={
            notFound
              ? "This incident does not exist or is no longer available."
              : "The incident could not be loaded. Please try again."
          }
        />
        <div className="pb-8 text-center">
          <BackLink to={incidentsPath} />
        </div>
      </section>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <BackLink to={incidentsPath} />
      </div>

      <section className="rounded-lg border border-border bg-surface-raised p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-caption font-semibold uppercase text-text-muted">
              Incident
            </p>
            <h1 className="mt-2 text-h2 font-semibold text-text-primary">
              {incident.village || "Unknown village"}
            </h1>
            <p className="mt-1 text-body text-text-muted">
              {incident.condition}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge
              label={incident.source}
              variant={sourceVariant(incident.source)}
            />
            {!incident.matched ? (
              <StatusBadge label="Needs verification" variant="warning" />
            ) : null}
            {incident.duplicate_flag === "possible" ? (
              <StatusBadge label="Possible duplicate" variant="warning" />
            ) : null}
          </div>
        </div>

        <dl className="mt-5 grid gap-4 border-t border-border pt-5 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Event date
            </dt>
            <dd className="mt-1 text-small text-text-primary">
              {formatDate(incident.event_date)}
              {incident.event_time ? ` at ${incident.event_time.slice(0, 5)}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Published
            </dt>
            <dd className="mt-1 text-small text-text-primary">
              {formatRelativeTime(incident.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Source reference
            </dt>
            <dd className="mt-1 text-small text-text-primary">
              {incident.source_reference || "No data"}
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Data worker
            </dt>
            <dd className="mt-1 text-small text-text-primary">
              {incident.worker_name || "No data"}
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded-lg border border-border bg-surface-raised p-5">
        <h2 className="text-h4 font-semibold text-text-primary">Report</h2>
        <p className="mt-3 whitespace-pre-wrap text-body text-text-primary">
          {incident.khabar}
        </p>
        <div className="mt-5 border-t border-border pt-5">
          <h3 className="text-small font-semibold text-text-primary">Note</h3>
          <p className="mt-2 whitespace-pre-wrap text-small text-text-muted">
            {incident.note || "No data"}
          </p>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface-raised p-5">
        <h2 className="text-h4 font-semibold text-text-primary">
          Casualty demographics
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {casualtyFields.map(({ key, label }) => (
            <div
              key={key}
              className="rounded-md border border-border bg-surface p-4"
            >
              <p className="text-caption font-semibold uppercase text-text-muted">
                {label}
              </p>
              <p className="mt-2 text-h4 font-semibold text-text-primary">
                {incident.casualty_demographics[key] ?? "No data"}
              </p>
            </div>
          ))}
        </div>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Total deaths", incident.total_deaths],
            ["Total injuries", incident.total_injuries],
            ["Reported deaths", incident.deaths],
            ["Reported injuries", incident.injuries],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-md bg-surface-muted p-3">
              <dt className="text-caption text-text-muted">{label}</dt>
              <dd className="mt-1 font-semibold text-text-primary">
                {value ?? "No data"}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-lg border border-border bg-surface-raised p-5">
        <h2 className="text-h4 font-semibold text-text-primary">
          Record information
        </h2>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Ministry of Health
            </dt>
            <dd className="mt-1 text-small text-text-primary">
              {incident.moh || "No data"}
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">
              Martyrs
            </dt>
            <dd className="mt-1 whitespace-pre-wrap text-small text-text-primary">
              {incident.martyrs || "No data"}
            </dd>
          </div>
          {[incident.source_link, incident.source_link_2].map((link, index) => (
            <div key={index}>
              <dt className="text-caption font-semibold uppercase text-text-muted">
                Source link {index + 1}
              </dt>
              <dd className="mt-1 text-small">
                {link ? (
                  <a
                    className="font-semibold text-accent hover:text-accent-hover"
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open source
                  </a>
                ) : (
                  <span className="text-text-primary">No data</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="space-y-3">
        <h2 className="text-h4 font-semibold text-text-primary">
          Incident categories
        </h2>
        {emptyCategories.map(({ key, label }) => (
          <details
            key={key}
            className="rounded-lg border border-border bg-surface-raised"
          >
            <summary className="cursor-pointer px-5 py-4 text-small font-semibold text-text-primary">
              {label}
            </summary>
            {incident[key] === null ? (
              <EmptyState
                title="No data"
                description={`No ${label.toLowerCase()} information is recorded for this incident.`}
                className="min-h-0 border-t border-border py-6"
              />
            ) : null}
          </details>
        ))}
      </section>
    </div>
  );
};
