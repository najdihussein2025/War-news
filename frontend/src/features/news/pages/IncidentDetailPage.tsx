import { useContext, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Card, Dialog, EmptyState, Input, Label } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { formatDate, formatDateTime, formatRelativeTime } from "../../../lib/formatters";
import { mockIncidentDetails } from "../../../mocks/mockIncidentDetails";
import { useIncidents } from "../../../mocks/useIncidents";
import type { IncidentStatus, MockIncident } from "../../../mocks/mockIncidents";
import { labelFor } from "../fieldLabels";
import {
  incidentFieldGroups,
  isReported,
  recordInfoFields,
  reportedCount,
  type FieldDef,
  type IncidentDetails,
} from "../incidentSchema";

const statusLabel: Record<IncidentStatus, string> = {
  approved: "Approved",
  rejected: "Rejected",
  archived: "Archived",
};

const statusVariant = (status: IncidentStatus) =>
  status === "approved" ? "success" : status === "rejected" ? "danger" : "neutral";

const sourceVariant = (source: MockIncident["source"]) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg
    className={cn("h-4 w-4 shrink-0 text-text-muted transition-transform duration-150 ease-out", open && "rotate-180")}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="m6 9 6 6 6-6" />
  </svg>
);

const DidValue = ({ def, details }: { def: FieldDef; details: IncidentDetails }) => {
  const flagSet = Number(details[def.controlledBy!] ?? 0) === 1;
  if (!flagSet) {
    // Locked, not missing: the controlling flag is 0 so no assessment applies.
    return (
      <span className="text-small text-text-muted" title="Not applicable — controlling flag is not set">
        —
      </span>
    );
  }
  const value = details[def.name] === "D" ? "D" : "ID";
  return (
    <StatusBadge
      label={value === "D" ? "D · Definite" : "ID · Indefinite"}
      variant={value === "D" ? "accent" : "warning"}
    />
  );
};

const FieldValue = ({ def, details }: { def: FieldDef; details: IncidentDetails }) => {
  if (def.kind === "did") {
    return <DidValue def={def} details={details} />;
  }

  if (def.kind === "flag") {
    const set = Number(details[def.name] ?? 0) === 1;
    return set ? (
      <span className="text-small font-medium text-text-primary">Yes</span>
    ) : (
      <span className="text-small text-text-muted">No</span>
    );
  }

  if (def.kind === "count") {
    const value = Number(details[def.name] ?? 0);
    return (
      <span
        className={cn(
          "text-right text-small tabular-nums",
          value === 0
            ? "text-text-muted"
            : def.emphasis === "deaths"
              ? "font-semibold text-text-primary"
              : def.emphasis === "injuries"
                ? "font-semibold text-gray-700"
                : "font-medium text-text-primary",
        )}
      >
        {value}
      </span>
    );
  }

  const value = details[def.name];
  return typeof value === "string" && value.trim() !== "" ? (
    <span className="text-right text-small text-text-primary">{value}</span>
  ) : (
    <span className="text-small text-text-muted">—</span>
  );
};

const DetailSection = ({
  name,
  fields,
  details,
}: {
  name: string;
  fields: FieldDef[];
  details: IncidentDetails;
}) => {
  const reported = fields.filter((def) => isReported(details, def)).length;
  const [open, setOpen] = useState(reported > 0);
  const contentId = `section-${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;

  return (
    <Card>
      <button
        type="button"
        className="flex min-h-11 w-full items-center justify-between gap-4 px-5 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="flex items-center gap-3">
          <span
            className={cn("h-2 w-2 shrink-0 rounded-full", reported > 0 ? "bg-accent" : "bg-border")}
            aria-hidden="true"
          />
          <span className="text-body font-semibold text-text-primary">{name}</span>
        </span>
        <span className="flex items-center gap-3">
          <span className={cn("text-caption", reported > 0 ? "font-semibold text-accent" : "text-text-muted")}>
            {reported > 0 ? `${reported} field${reported === 1 ? "" : "s"} reported` : "No data"}
          </span>
          <ChevronIcon open={open} />
        </span>
      </button>
      {open ? (
        <div
          id={contentId}
          className="grid gap-x-8 gap-y-1 border-t border-border px-5 py-4 sm:grid-cols-2 xl:grid-cols-3"
        >
          {fields.map((def) => (
            <div key={def.name} className="flex min-h-8 items-baseline justify-between gap-3">
              <span className={cn("text-small", isReported(details, def) ? "text-text-primary" : "text-text-muted")}>
                {labelFor(def.name)}
              </span>
              <FieldValue def={def} details={details} />
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
};

const editInputClasses =
  "h-9 w-full rounded-md border border-input-border bg-input-bg px-3 text-small text-text-primary transition-colors duration-150 ease-out hover:border-input-border-hover focus:border-input-border-focus focus:outline-none focus:ring-2 focus:ring-focus-ring focus:ring-offset-1 focus:ring-offset-surface-raised disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-text-muted";

const EditField = ({
  def,
  draft,
  onChange,
}: {
  def: FieldDef;
  draft: IncidentDetails;
  onChange: (name: string, value: number | string) => void;
}) => {
  const id = `edit-${def.name}`;
  const label = labelFor(def.name);

  if (def.kind === "flag") {
    return (
      <div className="space-y-1">
        <Label htmlFor={id} className="text-caption font-semibold text-text-muted">{label}</Label>
        <select
          id={id}
          className={editInputClasses}
          value={Number(draft[def.name] ?? 0)}
          onChange={(event) => onChange(def.name, Number(event.target.value))}
        >
          <option value={0}>No</option>
          <option value={1}>Yes</option>
        </select>
      </div>
    );
  }

  if (def.kind === "did") {
    const locked = Number(draft[def.controlledBy!] ?? 0) !== 1;
    return (
      <div className="space-y-1">
        <Label htmlFor={id} className="text-caption font-semibold text-text-muted">{label}</Label>
        <select
          id={id}
          className={editInputClasses}
          value={locked ? "" : String(draft[def.name] ?? "D")}
          disabled={locked}
          title={locked ? "Enable the controlling flag first" : undefined}
          onChange={(event) => onChange(def.name, event.target.value)}
        >
          <option value="">—</option>
          <option value="D">D (Definite)</option>
          <option value="ID">ID (Indefinite)</option>
        </select>
      </div>
    );
  }

  if (def.kind === "count") {
    return (
      <div className="space-y-1">
        <Label htmlFor={id} className="text-caption font-semibold text-text-muted">{label}</Label>
        <Input
          id={id}
          type="number"
          min={0}
          className="h-9 text-small"
          value={Number(draft[def.name] ?? 0)}
          onChange={(event) => onChange(def.name, Number(event.target.value))}
        />
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-caption font-semibold text-text-muted">{label}</Label>
      <Input
        id={id}
        className="h-9 text-small"
        value={String(draft[def.name] ?? "")}
        onChange={(event) => onChange(def.name, event.target.value)}
      />
    </div>
  );
};

const EditIncidentDialog = ({
  incident,
  details,
  onClose,
  onSave,
}: {
  incident: MockIncident;
  details: IncidentDetails;
  onClose: () => void;
  onSave: () => void;
}) => {
  const [core, setCore] = useState({
    village: incident.village,
    condition: incident.condition,
    event_date: incident.event_date.slice(0, 10),
    event_time: incident.event_date.slice(11, 16),
    khabar: incident.khabar,
  });
  const [draft, setDraft] = useState<IncidentDetails>({ ...details });

  const setValue = (name: string, value: number | string) =>
    setDraft((current) => ({ ...current, [name]: value }));

  return (
    <Dialog title={`Edit incident — ${incident.village}`} size="panel" onClose={onClose}>
      <form
        className="space-y-6"
        onSubmit={(event) => {
          event.preventDefault();
          onSave();
        }}
      >
        <fieldset className="rounded-lg border border-border p-4">
          <legend className="px-2 text-small font-semibold text-text-primary">Core incident</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="edit-village" className="text-caption font-semibold text-text-muted">Village</Label>
              <Input id="edit-village" className="h-9 text-small" value={core.village} onChange={(event) => setCore({ ...core, village: event.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="edit-condition" className="text-caption font-semibold text-text-muted">Condition</Label>
              <Input id="edit-condition" className="h-9 text-small" value={core.condition} onChange={(event) => setCore({ ...core, condition: event.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="edit-event-date" className="text-caption font-semibold text-text-muted">Event date</Label>
              <Input id="edit-event-date" type="date" className="h-9 text-small" value={core.event_date} onChange={(event) => setCore({ ...core, event_date: event.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="edit-event-time" className="text-caption font-semibold text-text-muted">Event time</Label>
              <Input id="edit-event-time" type="time" className="h-9 text-small" value={core.event_time} onChange={(event) => setCore({ ...core, event_time: event.target.value })} />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="edit-khabar" className="text-caption font-semibold text-text-muted">Khabar</Label>
              <textarea
                id="edit-khabar"
                className={cn(editInputClasses, "h-auto min-h-20 py-2")}
                value={core.khabar}
                onChange={(event) => setCore({ ...core, khabar: event.target.value })}
              />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="edit-note" className="text-caption font-semibold text-text-muted">Note</Label>
              <textarea
                id="edit-note"
                className={cn(editInputClasses, "h-auto min-h-16 py-2")}
                value={String(draft.note ?? "")}
                onChange={(event) => setValue("note", event.target.value)}
              />
            </div>
            {recordInfoFields.map((def) => (
              <EditField key={def.name} def={def} draft={draft} onChange={setValue} />
            ))}
          </div>
        </fieldset>

        {incidentFieldGroups.map((group) => (
          <fieldset key={group.name} className="rounded-lg border border-border p-4">
            <legend className="px-2 text-small font-semibold text-text-primary">{group.name}</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {group.fields.map((def) => (
                <EditField key={def.name} def={def} draft={draft} onChange={setValue} />
              ))}
            </div>
          </fieldset>
        ))}

        <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-border bg-surface-raised px-6 py-4">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit">Save changes</Button>
        </div>
      </form>
    </Dialog>
  );
};

export const IncidentDetailPage = () => {
  const { incidentId } = useParams();
  const { data } = useIncidents();
  const shell = useContext(ShellContext);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isArchiveOpen, setIsArchiveOpen] = useState(false);
  const [isCompareOpen, setIsCompareOpen] = useState(false);

  const incident = useMemo(() => data.find((item) => item.id === incidentId), [data, incidentId]);
  const details = useMemo<IncidentDetails>(
    () => (incidentId ? mockIncidentDetails[incidentId] ?? {} : {}),
    [incidentId],
  );

  const isEditOpen = searchParams.get("edit") === "1";
  const setEditOpen = (open: boolean) => {
    const next = new URLSearchParams(searchParams);
    if (open) {
      next.set("edit", "1");
    } else {
      next.delete("edit");
    }
    setSearchParams(next, { replace: true });
  };

  if (!incident) {
    return (
      <Card>
        <EmptyState
          title="Incident not found"
          description="The record may have been removed or the link is out of date."
        />
        <div className="flex justify-center pb-8">
          <Button type="button" variant="secondary" onClick={() => navigate("/incidents")}>
            Back to incidents
          </Button>
        </div>
      </Card>
    );
  }

  const reportedTotal = incidentFieldGroups.reduce((sum, group) => sum + reportedCount(details, group), 0);
  const note = typeof details.note === "string" ? details.note : "";
  const martyrs = typeof details.martyrs === "string" ? details.martyrs : "";
  const sourceLinks = [details.source_link, details.source_link_2].filter(
    (link): link is string => typeof link === "string" && link !== "",
  );

  return (
    <div className="space-y-5">
      <Link
        to="/incidents"
        className="inline-flex items-center gap-2 rounded-md text-small font-semibold text-text-muted transition-colors duration-150 ease-out hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        ← Back to incidents
      </Link>

      <Card className="p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-h3 font-semibold text-text-primary">{incident.village}</h2>
              <StatusBadge label={statusLabel[incident.status]} variant={statusVariant(incident.status)} />
              {!incident.matched ? <StatusBadge label="Needs verification" variant="warning" /> : null}
              {incident.duplicate_flag === "possible" ? (
                <StatusBadge label="Possible duplicate" variant="warning" />
              ) : null}
            </div>
            <p className="text-small text-text-muted">
              <span className="font-semibold text-text-primary">{incident.condition}</span>
              {" · "}{formatDateTime(incident.event_date)}
              {" · "}{reportedTotal} detail field{reportedTotal === 1 ? "" : "s"} reported
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" className="h-9" onClick={() => setEditOpen(true)}>
              Edit
            </Button>
            {incident.duplicate_flag === "possible" ? (
              <Button type="button" variant="secondary" className="h-9" onClick={() => setIsCompareOpen(true)}>
                Compare duplicate
              </Button>
            ) : null}
            {incident.status !== "archived" ? (
              <Button type="button" variant="ghost" className="h-9 text-danger" onClick={() => setIsArchiveOpen(true)}>
                Archive
              </Button>
            ) : null}
          </div>
        </div>

        <dl className="mt-5 grid gap-x-8 gap-y-4 border-t border-border pt-5 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">Source</dt>
            <dd className="mt-1 space-y-1">
              <StatusBadge label={incident.source} variant={sourceVariant(incident.source)} />
              <p className="text-caption text-text-muted">{incident.source_reference}</p>
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">Published</dt>
            <dd className="mt-1 text-small text-text-primary">
              {formatRelativeTime(incident.created_at)}
              <p className="text-caption text-text-muted">by {incident.reviewed_by ?? "—"}</p>
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">Data worker</dt>
            <dd className={cn("mt-1 text-small", details.worker_name ? "text-text-primary" : "text-text-muted")}>
              {String(details.worker_name ?? "—")}
            </dd>
          </div>
          <div>
            <dt className="text-caption font-semibold uppercase text-text-muted">MoH cross-checked</dt>
            <dd className="mt-1 text-small">
              {Number(details.moh ?? 0) === 1 ? (
                <span className="font-medium text-text-primary">Yes</span>
              ) : (
                <span className="text-text-muted">No</span>
              )}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-caption font-semibold uppercase text-text-muted">Martyrs</dt>
            <dd className={cn("mt-1 text-small", martyrs ? "font-medium text-text-primary" : "text-text-muted")}>
              {martyrs || "None recorded"}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-caption font-semibold uppercase text-text-muted">Source links</dt>
            <dd className="mt-1 space-y-1">
              {sourceLinks.length > 0 ? (
                sourceLinks.map((link) => (
                  <a
                    key={link}
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-small font-medium text-accent underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  >
                    {link}
                  </a>
                ))
              ) : (
                <span className="text-small text-text-muted">—</span>
              )}
            </dd>
          </div>
        </dl>

        <div className="mt-5 border-t border-border pt-5">
          <p className="text-caption font-semibold uppercase text-text-muted">Khabar (original report)</p>
          <p className="mt-2 text-body text-text-primary">{incident.khabar}</p>
          <p className="mt-4 text-caption font-semibold uppercase text-text-muted">Note</p>
          <p className={cn("mt-2 text-small", note ? "text-text-primary" : "text-text-muted")}>
            {note || "No note recorded."}
          </p>
        </div>
      </Card>

      <div className="space-y-3">
        {incidentFieldGroups.map((group) => (
          <DetailSection
            key={`${incident.id}-${group.name}`}
            name={group.name}
            fields={group.fields}
            details={details}
          />
        ))}
      </div>

      {isEditOpen ? (
        <EditIncidentDialog
          incident={incident}
          details={details}
          onClose={() => setEditOpen(false)}
          onSave={() => {
            setEditOpen(false);
            shell?.showToast("Edit is mocked for now — changes are not persisted.");
          }}
        />
      ) : null}

      {isArchiveOpen ? (
        <Dialog title="Archive incident" onClose={() => setIsArchiveOpen(false)}>
          <p className="text-small text-text-muted">
            Archiving removes <span className="font-semibold text-text-primary">{incident.village} — {formatDate(incident.event_date)}</span> from
            the active feed. The record stays available in exports and the archive filter.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setIsArchiveOpen(false)}>Cancel</Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setIsArchiveOpen(false);
                shell?.showToast("Archive is mocked for now.");
              }}
            >
              Archive
            </Button>
          </div>
        </Dialog>
      ) : null}

      {isCompareOpen ? (
        <Dialog title="Compare possible duplicate" size="lg" onClose={() => setIsCompareOpen(false)}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-border bg-surface p-4">
              <StatusBadge label="Published incident" variant="accent" />
              <h3 className="mt-3 text-h4 font-semibold text-text-primary">{incident.village}</h3>
              <p className="mt-2 text-small text-text-muted">{incident.khabar}</p>
              <p className="mt-4 text-caption text-text-muted">{incident.source} / {incident.source_reference}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <StatusBadge label="Suspected match" variant="warning" />
              <h3 className="mt-3 text-h4 font-semibold text-text-primary">{incident.village}</h3>
              <p className="mt-2 text-small text-text-muted">
                Earlier report with similar village, condition, and event window. Published for visibility after soft dedup flag.
              </p>
              <p className="mt-4 text-caption text-text-muted">mock:dedup-neighbor</p>
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Button type="button" onClick={() => shell?.showToast("Compare resolution is mocked for now.")}>
              Mark reviewed
            </Button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
};
