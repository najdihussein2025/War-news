import { isAxiosError } from "axios";
import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, ConfirmDialog, Dialog, EmptyState, Input, Label } from "../../../components/ui";
import { formatDate, formatRelativeTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { useIncidentQuery } from "../hooks";
import { deleteIncident, updateIncident } from "../api";
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
  const navigate = useNavigate();
  const { data: incident, isLoading, error, refetch } = useIncidentQuery(incidentId);
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [actionError, setActionError] = useState("");

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

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => { setActionError(""); setIsEditing(true); }}>
          Update
        </Button>
        <Button type="button" variant="destructive" onClick={() => { setActionError(""); setIsDeleting(true); }}>
          Delete
        </Button>
      </div>

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


      {isEditing ? (
        <Dialog title="Update incident" eyebrow="Edit record" size="lg" onClose={() => !isSaving && setIsEditing(false)}>
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!incidentId) return;
              const form = new FormData(event.currentTarget);
              const nullable = (name: string) => String(form.get(name) ?? "").trim() || null;
              const numberOrNull = (name: string) => {
                const value = String(form.get(name) ?? "").trim();
                return value === "" ? null : Number(value);
              };
              setIsSaving(true);
              setActionError("");
              try {
                await updateIncident(incidentId, {
                  event_date: String(form.get("event_date")),
                  event_time: nullable("event_time"),
                  khabar: String(form.get("khabar") ?? "").trim(),
                  note: nullable("note"),
                  worker_name: nullable("worker_name"),
                  source_link: nullable("source_link"),
                  source_link_2: nullable("source_link_2"),
                  total_deaths: numberOrNull("total_deaths"),
                  total_injuries: numberOrNull("total_injuries"),
                  deaths: numberOrNull("deaths"),
                  injuries: numberOrNull("injuries"),
                });
                await refetch();
                setIsEditing(false);
              } catch {
                setActionError("Could not update the incident. Please check the values and try again.");
              } finally {
                setIsSaving(false);
              }
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div><Label htmlFor="incident-date">Event date *</Label><Input id="incident-date" name="event_date" type="date" defaultValue={incident.event_date} required /></div>
              <div><Label htmlFor="incident-time">Event time</Label><Input id="incident-time" name="event_time" type="time" defaultValue={incident.event_time?.slice(0, 5) ?? ""} /></div>
            </div>
            <div><Label htmlFor="incident-report">Report *</Label><textarea id="incident-report" name="khabar" required defaultValue={incident.khabar} className="mt-1 min-h-36 w-full rounded-md border border-border bg-surface px-3 py-2 text-body" /></div>
            <div><Label htmlFor="incident-note">Note</Label><textarea id="incident-note" name="note" defaultValue={incident.note ?? ""} className="mt-1 min-h-24 w-full rounded-md border border-border bg-surface px-3 py-2 text-body" /></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><Label htmlFor="incident-worker">Data worker</Label><Input id="incident-worker" name="worker_name" defaultValue={incident.worker_name ?? ""} /></div>
              <div><Label htmlFor="incident-source-1">Source link 1</Label><Input id="incident-source-1" name="source_link" type="url" defaultValue={incident.source_link ?? ""} /></div>
              <div><Label htmlFor="incident-source-2">Source link 2</Label><Input id="incident-source-2" name="source_link_2" type="url" defaultValue={incident.source_link_2 ?? ""} /></div>
              {(["total_deaths", "total_injuries", "deaths", "injuries"] as const).map((field) => (
                <div key={field}><Label htmlFor={`incident-${field}`}>{field.split("_").map((word) => word[0].toUpperCase() + word.slice(1)).join(" ")}</Label><Input id={`incident-${field}`} name={field} type="number" min="0" defaultValue={incident[field] ?? ""} /></div>
              ))}
            </div>
            {actionError ? <p className="text-small text-danger">{actionError}</p> : null}
            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="secondary" disabled={isSaving} onClick={() => setIsEditing(false)}>Cancel</Button>
              <Button type="submit" isLoading={isSaving} loadingText="Updating">Update</Button>
            </div>
          </form>
        </Dialog>
      ) : null}

      {isDeleting ? (
        <ConfirmDialog
          title="Delete incident?"
          description="This incident will be removed from the active records."
          confirmLabel="Delete incident"
          destructive
          isLoading={isSaving}
          onCancel={() => !isSaving && setIsDeleting(false)}
          onConfirm={async () => {
            if (!incidentId) return;
            setIsSaving(true);
            try {
              await deleteIncident(incidentId);
              navigate(incidentsPath, { replace: true });
            } catch {
              setActionError("Could not delete the incident. Please try again.");
              setIsDeleting(false);
            } finally {
              setIsSaving(false);
            }
          }}
        />
      ) : null}
    </div>
  );
};
