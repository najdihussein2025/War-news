import { useMemo } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import {
  Button,
  DataTable,
  EmptyState,
  Input,
  Label,
  type DataTableColumn,
} from "../../../components/ui";
import { useLiveQueryTitleAddon } from "../../../hooks/useLiveQueryTitleAddon";
import { formatDate, formatRelativeTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { useIncidentsQuery } from "../hooks";
import type { Incident, IncidentSource } from "../types";

const PAGE_SIZE = 25;

const sourceVariant = (source: IncidentSource) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

export const IncidentsPage = () => {
  const navigate = useNavigate();
  const roleBase = roleBaseFromPath(useLocation().pathname);
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const offset = (page - 1) * PAGE_SIZE;
  const village = params.get("village") ?? "";
  const sourceType = params.get("source_type") ?? "";
  const eventDateFrom = params.get("event_date_from") ?? "";
  const eventDateTo = params.get("event_date_to") ?? "";
  const flaggedOnly = params.get("flagged_only") === "true";
  const hasFilters = Boolean(
    village || sourceType || eventDateFrom || eventDateTo || flaggedOnly,
  );

  const filters = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      village,
      sourceType,
      eventDateFrom,
      eventDateTo,
      flaggedOnly,
    }),
    [
      eventDateFrom,
      eventDateTo,
      flaggedOnly,
      offset,
      sourceType,
      village,
    ],
  );

  const { data, isLoading, isError, dataUpdatedAt, isFetching } =
    useIncidentsQuery(filters);
  useLiveQueryTitleAddon(dataUpdatedAt, isFetching);
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
  const flaggedCount = rows.filter((incident) => !incident.matched).length;
  const duplicateCount = rows.filter(
    (incident) => incident.duplicate_flag === "possible",
  ).length;

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
      key: "village",
      header: "Village",
      render: (row) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-text-primary">
              {row.village || "Unknown village"}
            </span>
            {!row.matched ? (
              <StatusBadge label="Needs verification" variant="warning" />
            ) : null}
            {row.duplicate_flag === "possible" ? (
              <StatusBadge label="Possible duplicate" variant="warning" />
            ) : null}
          </div>
          <p className="max-w-xl text-caption text-text-muted">{row.khabar}</p>
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
      key: "condition",
      header: "Condition",
      render: (row) => row.condition,
    },
    {
      key: "date",
      header: "Date",
      render: (row) => formatDate(row.event_date),
    },
    {
      key: "source",
      header: "Source",
      render: (row) => (
        <div className="space-y-1">
          <StatusBadge label={row.source} variant={sourceVariant(row.source)} />
          {row.source_reference ? (
            <p className="text-caption text-text-muted">{row.source_reference}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "created",
      header: "Published",
      render: (row) => formatRelativeTime(row.created_at),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Needs verification on this page
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {flaggedCount}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Possible duplicates on this page
          </p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">
            {duplicateCount}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface-raised p-4">
        <div className="grid gap-4 lg:grid-cols-4">
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
            <Label htmlFor="incident-source-filter">Source</Label>
            <select
              id="incident-source-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={sourceType}
              onChange={(event) => updateParam("source_type", event.target.value)}
            >
              <option value="">All sources</option>
              <option value="telegram">Telegram</option>
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
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="flex h-11 items-center gap-3 rounded-md border border-border bg-surface px-3 text-small font-semibold text-text-primary">
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
            Show flagged only
          </label>
          {hasFilters ? (
            <Button
              type="button"
              variant="ghost"
              className="h-9"
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
            className="h-9"
            onClick={() => navigate(`${roleBase}/incidents/${row.id}`)}
          >
            View
          </Button>
        )}
      />

      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-small text-text-muted">
            Page {page} of {totalPages} · {total} records
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
    </div>
  );
};
