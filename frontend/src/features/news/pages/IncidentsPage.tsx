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
  Select,
  type DataTableColumn,
  type SelectOption,
} from "../../../components/ui";
import { useLiveQueryTitleAddon } from "../../../hooks/useLiveQueryTitleAddon";
import { formatDate, formatDateTime } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { ConditionSelect } from "../components/ConditionSelect";
import { useConditionsQuery, useIncidentsQuery, useVillagesQuery } from "../hooks";
import { createIncident } from "../api";
import type { Incident, IncidentSource } from "../types";

const PAGE_SIZE = 25;

const sourceVariant = (source: IncidentSource) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

const PlusIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none">
    <path
      d="M10 4.167v11.666M4.167 10h11.666"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

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
  const {
    data: conditions = [],
    isLoading: isConditionsLoading,
    isError: isConditionsError,
  } = useConditionsQuery();
  const {
    data: villages = [],
    isLoading: isVillagesLoading,
  } = useVillagesQuery();
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
  const verificationOptions: SelectOption[] = [
    { value: "needs_verification", label: "Needs verification" },
    { value: "matched", label: "Matched" },
  ];
  const sourceOptions: SelectOption[] = [
    { value: "telegram", label: "Telegram" },
    { value: "twitter", label: "Twitter" },
    { value: "facebook", label: "Facebook" },
    { value: "website", label: "Website" },
    { value: "manual", label: "Manual" },
  ];

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
    <div className="space-y-6">
      <section className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-1">
            <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
              Incident operations
            </p>
            <h1 className="text-h3 font-semibold text-text-primary">
              Incidents
            </h1>
          </div>
          {isFetching ? (
            <p className="text-small text-text-muted">
              Refreshing incident feed...
            </p>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)]">
          <p className="text-caption font-semibold uppercase text-text-muted">
            {hasFilters ? "Matching incidents" : "Total incidents"}
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {total}
          </p>
          </div>
          <div className="rounded-xl border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)]">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Needs verification
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {flaggedCount}
          </p>
          </div>
          <div className="rounded-xl border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)]">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Possible duplicates
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {duplicateCount}
          </p>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-[1.125rem] border border-border bg-surface-raised shadow-raised">
        <div className="flex flex-col gap-4 border-b border-border bg-[linear-gradient(180deg,rgba(234,242,251,0.82)_0%,rgba(255,255,255,0.98)_100%)] px-4 py-4 sm:px-5 lg:flex-row lg:items-end lg:justify-between lg:px-6">
          <div className="space-y-2">
            <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
              Incident workspace
            </p>
            <h2 className="text-h4 font-semibold text-text-primary">
              Refine the incident list
            </h2>
          </div>
          <Button
            className="h-12 w-full rounded-xl px-5 sm:w-auto"
            type="button"
            onClick={() => {
              setCreateError("");
              setIsCreateOpen(true);
            }}
          >
            <PlusIcon />
            Create incident
          </Button>
        </div>

        <div className="px-4 py-4 sm:px-5 sm:py-5 lg:px-6">
          <div className="grid gap-x-6 gap-y-5 md:grid-cols-2 xl:grid-cols-4 xl:gap-x-8 xl:gap-y-6">
          <div className="space-y-2 xl:col-span-1">
            <Label htmlFor="incident-village-filter">Village</Label>
            <Select
              id="incident-village-filter"
              value={village}
              options={villages}
              searchable
              searchPlaceholder="Search village in English or Arabic"
              placeholder={isVillagesLoading && villages.length === 0 ? "Loading villages..." : "All villages"}
              className="w-full min-w-0"
              disabled={isVillagesLoading && villages.length === 0}
              onChange={(value) => updateParam("village", value)}
            />
          </div>
          <div className="space-y-2 xl:col-span-1">
            <Label htmlFor="incident-condition-filter">Condition</Label>
            <ConditionSelect
              id="incident-condition-filter"
              value={condition}
              conditions={conditions}
              isLoading={isConditionsLoading}
              disabled={isConditionsLoading && conditions.length === 0}
              placeholder="All conditions"
              className="w-full min-w-0"
              onChange={(value) => updateParam("condition", value)}
            />
            {isConditionsError ? (
              <p className="text-caption text-text-muted">
                Could not load condition options.
              </p>
            ) : null}
          </div>
          <div className="space-y-2 xl:col-span-1">
            <Label htmlFor="incident-verification-filter">Verification</Label>
            <Select
              id="incident-verification-filter"
              value={verificationStatus}
              placeholder="All verification states"
              options={verificationOptions}
              className="w-full"
              onChange={(value) => updateParam("verification_status", value)}
            />
          </div>
          <div className="space-y-2 xl:col-span-1">
            <Label htmlFor="incident-source-filter">Source</Label>
            <Select
              id="incident-source-filter"
              value={sourceType}
              placeholder="All sources"
              options={sourceOptions}
              className="w-full"
              onChange={(value) => updateParam("source_type", value)}
            />
          </div>
          <div className="space-y-2 xl:col-span-1">
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
          <div className="space-y-2 xl:col-span-1">
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
          <div className="mt-6 flex flex-col gap-3 rounded-2xl border border-border bg-surface p-3 sm:p-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <label className="flex min-h-[3rem] w-full items-center gap-3 rounded-xl border border-border bg-surface-raised px-3.5 py-2.5 text-small font-semibold text-text-primary shadow-[0_1px_2px_rgba(11,34,54,0.04)] transition-colors hover:border-input-border-hover hover:bg-surface sm:w-auto">
              <input
                type="checkbox"
                checked={flaggedOnly}
                onChange={(event) =>
                  updateParam(
                    "flagged_only",
                    event.target.checked ? "true" : "",
                  )
                }
                className="h-4 w-4 rounded border-border text-accent focus:ring-focus-ring"
              />
                <span className="leading-5">Show items needing attention</span>
              </label>
              {hasFilters ? (
                <Button
                  type="button"
                  variant="ghost"
                  className="h-11 w-full rounded-xl px-4 sm:w-auto"
                  onClick={() => setParams({})}
                >
                  Clear filters
                </Button>
              ) : null}
            </div>
            {hasFilters ? (
              <StatusBadge label="Filters active" variant="neutral" />
            ) : null}
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-h4 font-semibold text-text-primary">
              Incident records
            </h2>
            <p className="text-small text-text-muted">
              {total} result{total === 1 ? "" : "s"}
            </p>
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
      </section>

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
            <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="create-incident-village">Village *</Label>
                <Select
                  id="create-incident-village"
                  name="village"
                  required
                  options={villages}
                  searchable
                  searchPlaceholder="Search village in English or Arabic"
                  placeholder={isVillagesLoading && villages.length === 0 ? "Loading villages..." : "Select village"}
                  className="w-full min-w-0"
                  disabled={isVillagesLoading && villages.length === 0}
                  defaultValue=""
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="create-incident-condition">Condition *</Label>
                <ConditionSelect
                  id="create-incident-condition"
                  name="condition"
                  required
                  conditions={conditions}
                  isLoading={isConditionsLoading}
                  disabled={isConditionsLoading && conditions.length === 0}
                  placeholder="Select condition"
                  className="w-full min-w-0"
                  defaultValue=""
                />
              </div>
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
