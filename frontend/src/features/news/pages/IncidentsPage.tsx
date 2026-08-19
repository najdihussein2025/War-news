import { useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import {
  Button,
  DataTable,
  Dialog,
  EmptyState,
  Input,
  Label,
  type DataTableColumn,
} from "../../../components/ui";
import { useLiveQueryTitleAddon } from "../../../hooks/useLiveQueryTitleAddon";
import { formatDate, formatDateTime } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { useIncidentsQuery } from "../hooks";
import { createIncident } from "../api";
import type { Incident, IncidentSource } from "../types";

const PAGE_SIZE = 25;

const sourceVariant = (source: IncidentSource) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

export const IncidentsPage = () => {
  const navigate = useNavigate();
  const roleBase = roleBaseFromPath(useLocation().pathname);
  const [params, setParams] = useSearchParams();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const offset = (page - 1) * PAGE_SIZE;
  const village = params.get("village") ?? "";
  const condition = params.get("condition") ?? "";
  const sourceType = params.get("source_type") ?? "";
  const verificationStatus = params.get("verification_status") as "matched" | "needs_verification" | "";
  const eventDateFrom = params.get("event_date_from") ?? "";
  const eventDateTo = params.get("event_date_to") ?? "";
  const flaggedOnly = params.get("flagged_only") === "true";
  const hasFilters = Boolean(
    village || condition || sourceType || verificationStatus || eventDateFrom || eventDateTo || flaggedOnly,
  );

  const filters = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      village,
      condition,
      sourceType,
      verificationStatus: verificationStatus || undefined,
      eventDateFrom,
      eventDateTo,
      flaggedOnly,
    }),
    [
      condition,
      eventDateFrom,
      eventDateTo,
      flaggedOnly,
      offset,
      sourceType,
      verificationStatus,
      village,
    ],
  );

  const { data, isLoading, isError, isFetching, refetch } =
    useIncidentsQuery(filters);
  const verificationSummary = useIncidentsQuery({ limit: 1, offset: 0, verificationStatus: "needs_verification" });
  const duplicateSummary = useIncidentsQuery({ limit: 1, offset: 0, duplicateOnly: true });
  useLiveQueryTitleAddon(data?.latest_incident_at ?? null, isFetching);
  const rows = data?.items ?? [];
  const total = data?.total ?? 0;

  // Collect raw_message_ids that appear on more than one incident in the current
  // page — these share the same source bulletin (multi-village extraction).
  const sharedBulletinIds = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of rows) {
      if (row.raw_message_id != null) {
        counts.set(row.raw_message_id, (counts.get(row.raw_message_id) ?? 0) + 1);
      }
    }
    const shared = new Set<number>();
    for (const [id, count] of counts) {
      if (count > 1) shared.add(id);
    }
    return shared;
  }, [rows]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const flaggedCount = verificationSummary.data?.total ?? 0;
  const duplicateCount = duplicateSummary.data?.total ?? 0;

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.delete("page");
    setParams(next);
  };

  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    if (nextPage <= 1) {
      next.delete("page");
    } else {
      next.set("page", String(nextPage));
    }
    setParams(next);
  };

  const columns: Array<DataTableColumn<Incident>> = [
    {
      key: "number",
      header: "#",
      className: "w-14 tabular-nums text-text-muted",
      render: (row) => offset + rows.indexOf(row) + 1,
    },
    {
      key: "village",
      header: "Village",
      render: (row) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-text-primary">
              {row.village || "Unknown village"}
            </span>
            {row.duplicate_flag === "possible" ? (
              <StatusBadge label="Possible duplicate" variant="warning" />
            ) : null}
            {row.details_pending ? (
              <StatusBadge label="Details pending" variant="neutral" />
            ) : null}
          </div>
          <p className="max-w-xl break-words text-caption text-text-muted" dir="auto">{row.khabar.length > 180 ? `${row.khabar.slice(0, 180)}…` : row.khabar}</p>
          {row.raw_message_id != null &&
            sharedBulletinIds.has(row.raw_message_id) ? (
            <p className="text-caption text-text-muted">
              Source: same bulletin as another village on this page
            </p>
          ) : null}
        </div>
      ),
    },
    {
      key: "verification",
      header: "Verification",
      render: (row) => <StatusBadge label={row.matched ? "Matched" : "Needs verification"} variant={row.matched ? "success" : "warning"} />,
    },
    {
      key: "condition",
      header: "Condition",
      render: (row) => row.condition,
    },
    {
      key: "date",
      header: "Event date / time",
      render: (row) => <div><p>{formatDate(row.event_date)}</p><p className="mt-1 text-caption text-text-muted">{row.event_time ? row.event_time.slice(0, 5) : "Time not recorded"}</p></div>,
    },
    {
      key: "source",
      header: "Source",
      render: (row) => (
        <div className="space-y-1">
          <StatusBadge label={row.source} variant={sourceVariant(row.source)} />
          {row.source_reference ? (
            <p className="break-all text-caption text-text-muted">{row.source_reference}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "created",
      header: "Received",
      render: (row) => formatDateTime(row.created_at),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">
            {hasFilters ? "Matching incidents" : "Total incidents"}
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {total}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Needs verification
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {flaggedCount}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Possible duplicates
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {duplicateCount}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface-raised p-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="incident-village-filter">Village</Label>
            <Input
              id="incident-village-filter"
              value={village}
              onChange={(event) => updateParam("village", event.target.value)}
              placeholder="Search village"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident-condition-filter">Condition</Label>
            <Input id="incident-condition-filter" value={condition} onChange={(event) => updateParam("condition", event.target.value)} placeholder="Search condition" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident-verification-filter">Verification</Label>
            <select id="incident-verification-filter" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary" value={verificationStatus} onChange={(event) => updateParam("verification_status", event.target.value)}>
              <option value="">All verification states</option>
              <option value="needs_verification">Needs verification</option>
              <option value="matched">Matched</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident-source-filter">Source</Label>
            <select
              id="incident-source-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={sourceType}
              onChange={(event) => updateParam("source_type", event.target.value)}
            >
              <option value="">All sources</option>
              <option value="telegram">Telegram</option>
              <option value="twitter">Twitter</option>
              <option value="facebook">Facebook</option>
              <option value="website">Website</option>
              <option value="api">API</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident-from-filter">From</Label>
            <Input
              id="incident-from-filter"
              type="date"
              value={eventDateFrom}
              onChange={(event) =>
                updateParam("event_date_from", event.target.value)
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident-to-filter">To</Label>
            <Input
              id="incident-to-filter"
              type="date"
              value={eventDateTo}
              onChange={(event) =>
                updateParam("event_date_to", event.target.value)
              }
            />
          </div>
        </div>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <label className="flex h-11 w-full items-center gap-3 rounded-md border border-border bg-surface px-3 text-small font-semibold text-text-primary sm:w-auto">
            <input
              type="checkbox"
              checked={flaggedOnly}
              onChange={(event) =>
                updateParam(
                  "flagged_only",
                  event.target.checked ? "true" : "",
                )
              }
            />
            Show items needing attention
          </label>
          <Button className="w-full sm:w-auto" type="button" onClick={() => { setCreateError(""); setIsCreateOpen(true); }}>
            Create
          </Button>
          {hasFilters ? (
            <Button
              type="button"
              variant="ghost"
              className="h-9 w-full sm:w-auto"
              onClick={() => setParams({})}
            >
              Clear filters
            </Button>
          ) : null}
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(row) => row.id}
        loading={isLoading}
        error={isError}
        minWidth="1100px"
        clientSort={false}
        emptyState={
          <EmptyState
            title={hasFilters ? "No matching incidents" : "No incidents yet"}
            description={
              hasFilters
                ? "Adjust or clear the filters to broaden the results."
                : "Materialized incidents will appear here."
            }
          />
        }
        errorState={
          <EmptyState
            title="Could not load incidents"
            description="The incidents list could not be loaded. Please try again."
          />
        }
        actions={(row) => (
          <Button
            type="button"
            variant="secondary"
            className="h-9 w-full sm:w-auto"
            onClick={() => navigate(`${roleBase}/incidents/${row.id}`)}
          >
            View details
          </Button>
        )}
      />

      {total > PAGE_SIZE ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-small text-text-muted">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total} incidents · Page {page} of {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}

      {isCreateOpen ? (
        <Dialog title="Create incident" eyebrow="Create record" size="lg" onClose={() => !isCreating && setIsCreateOpen(false)}>
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const nullable = (name: string) => String(form.get(name) ?? "").trim() || null;
              setIsCreating(true);
              setCreateError("");
              try {
                await createIncident({
                  village: String(form.get("village") ?? "").trim(),
                  condition: String(form.get("condition") ?? "").trim(),
                  event_date: String(form.get("event_date")),
                  event_time: nullable("event_time"),
                  khabar: String(form.get("khabar") ?? "").trim(),
                  note: nullable("note"),
                  source_link: nullable("source_link"),
                });
                setIsCreateOpen(false);
                setPage(1);
                await refetch();
              } catch (error) {
                setCreateError(isAxiosError(error) && typeof error.response?.data?.detail === "string" ? error.response.data.detail : "Could not create the incident. Please try again.");
              } finally {
                setIsCreating(false);
              }
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label htmlFor="create-incident-village">Village *</Label><Input id="create-incident-village" name="village" placeholder="Existing village name" required /></div>
              <div className="space-y-2"><Label htmlFor="create-incident-condition">Condition *</Label><Input id="create-incident-condition" name="condition" placeholder="Existing condition name" required /></div>
              <div className="space-y-2"><Label htmlFor="create-incident-date">Event date *</Label><Input id="create-incident-date" name="event_date" type="date" defaultValue={getBeirutDate()} required /></div>
              <div className="space-y-2"><Label htmlFor="create-incident-time">Event time</Label><Input id="create-incident-time" name="event_time" type="time" /></div>
            </div>
            <div className="space-y-2"><Label htmlFor="create-incident-report">Report *</Label><textarea id="create-incident-report" name="khabar" required placeholder="Enter the complete incident report" className="min-h-36 w-full rounded-md border border-input-border bg-input-bg px-3 py-2 text-body text-text-primary" /></div>
            <div className="space-y-2"><Label htmlFor="create-incident-note">Note</Label><Input id="create-incident-note" name="note" /></div>
            <div className="space-y-2"><Label htmlFor="create-incident-source">Source link</Label><Input id="create-incident-source" name="source_link" type="url" placeholder="https://..." /></div>
            {createError ? <p className="text-small text-danger">{createError}</p> : null}
            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="secondary" disabled={isCreating} onClick={() => setIsCreateOpen(false)}>Cancel</Button>
              <Button type="submit" isLoading={isCreating} loadingText="Creating">Create</Button>
            </div>
          </form>
        </Dialog>
      ) : null}
    </div>
  );
};
