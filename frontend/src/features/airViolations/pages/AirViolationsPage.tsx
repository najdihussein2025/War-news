import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useSearchParams } from "react-router-dom";
import { Button, ConfirmDialog, DataTable, Dialog, EmptyState, Input, Label, Select, type DataTableColumn } from "../../../components/ui";
import { useLiveQueryTitleAddon } from "../../../hooks/useLiveQueryTitleAddon";
import { decodePageParam, encodePageParam } from "../../../lib/encryptedPageParam";
import { formatDate, formatDateTime } from "../../../lib/formatters";
import { getBeirutDate, normalizeDateInputValue } from "../../../lib/localDate";
import { useAuthStore } from "../../../stores/authStore";
import { useAirViolationSummaryQuery, useAirViolationsQuery } from "../hooks";
import { useVillagesQuery } from "../../news/hooks";
import { acquireAirViolationEditLock, createAirViolation, deleteAirViolation, exportAirViolations, releaseAirViolationEditLock, updateAirViolation } from "../api";
import type { AirViolation, AirViolationVillage } from "../types";
import { importAirViolationKhabar } from "../api";
import type { WorkbookImportSummary } from "../../news/api";

const PAGE_SIZE = 100;

const emptyText = "—";

const formatTime = (value: string | null) => {
  if (!value) {
    return emptyText;
  }
  return value.slice(0, 5);
};

const formatWindowId = (value: string | null) => {
  if (!value) {
    return emptyText;
  }
  const parts = value.split(":");
  if (parts.length < 5) {
    return value;
  }
  const caza = parts[1];
  const timestamp = parts.slice(2, 5).join(":");
  return `${caza} - ${formatDateTime(timestamp)}`;
};

const recordWindowRange = (row: AirViolation) => {
  if (row.window_start && row.window_end) {
    return `${formatDateTime(row.window_start)} to ${formatDateTime(row.window_end)}`;
  }
  return formatWindowId(row.window_id);
};

const villageList = (row: AirViolation | null) => {
  if (!row) return [];
  if (row.villages?.length) {
    return row.villages.filter((value) => value.name.trim() !== "");
  }
  const values: AirViolationVillage[] = [
    ...(row.village_en ? [{ village_id: row.village_id ?? null, name: row.village_en }] : []),
    ...(row.village_ar && row.village_ar !== row.village_en ? [{ village_id: row.village_id ?? null, name: row.village_ar }] : []),
  ];
  return values;
};

const displayVillages = villageList;

const DAILY_WINDOW_MINUTES = 24 * 60;

const windowLabel = (minutes: number) => {
  if (minutes === DAILY_WINDOW_MINUTES) return "Daily";
  if (minutes % 60 === 0) return `${minutes / 60}-hour window`;
  return `${minutes}-minute window`;
};

const windowRule = (row: AirViolation) => {
  if (row.condition_id !== 35 && row.condition_id !== 36) return null;
  if (!row.window_duration_minutes) {
    return row.condition_id === 36 ? "Caza review required" : null;
  }
  return windowLabel(row.window_duration_minutes);
};

const isWindowedActivity = (row: AirViolation) => (
  (row.condition_id === 35 || row.condition_id === 36) && row.window_duration_minutes != null
);

const isPerReportBreach = (row: AirViolation) => row.condition_id === 34 || row.condition_id === 38;

const breachUnitLabel = (row: AirViolation) => (row.condition_id === 38 ? "villages" : "cazas");

const compactWindowRange = (row: AirViolation) => {
  if (!row.window_start || !row.window_end) return null;
  const startDate = row.window_start.slice(0, 10);
  const endDate = row.window_end.slice(0, 10);
  if (startDate === endDate) {
    return `${formatDate(startDate)} · ${formatTime(row.window_start.slice(11))}–${formatTime(row.window_end.slice(11))}`;
  }
  return recordWindowRange(row);
};

export const AirViolationsPage = () => {
  const [importMessage, setImportMessage] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<WorkbookImportSummary | null>(null);
  const [selectedViolation, setSelectedViolation] = useState<AirViolation | null>(null);
  const [returnToWindow, setReturnToWindow] = useState<AirViolation | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingViolation, setEditingViolation] = useState<AirViolation | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isFormDirty, setIsFormDirty] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [createError, setCreateError] = useState("");
  const [actionError, setActionError] = useState("");
  const currentUserId = useAuthStore((state) => state.user?.id ?? null);
  const [params, setParams] = useSearchParams();
  const importedOnly = params.get("imported_only") === "true";
  const page = decodePageParam(params.get("page"));
  const offset = (page - 1) * PAGE_SIZE;
  const conditionId = params.get("condition_id") ?? "";
  const eventDateFrom = normalizeDateInputValue(params.get("event_date_from"));
  const eventDateTo = normalizeDateInputValue(params.get("event_date_to"));
  const cazaEn = params.get("caza_en") ?? "";
  const village = params.get("village") ?? "";
  const lastHours = params.get("last_hours") ?? "";
  const sortOrder = (params.get("sort_order") as "newest" | "oldest" | null) ?? "newest";
  const effectiveEventDateFrom = eventDateFrom;
  const effectiveEventDateTo = eventDateTo;
  const hourPresets = ["1", "6", "12", "24", "48", "72", "168"];
  const [customHoursMode, setCustomHoursMode] = useState(
    lastHours !== "" && !hourPresets.includes(lastHours),
  );
  const hasFilters = Boolean(conditionId || eventDateFrom || eventDateTo || cazaEn || village || lastHours || sortOrder !== "newest");
  const closeEditor = async () => {
    if (isFormDirty) {
      setConfirmDiscard(true);
      return;
    }
    if (editingViolation) {
      await releaseAirViolationEditLock(editingViolation.id);
      await refetch();
    }
    setIsCreateOpen(false);
    setEditingViolation(null);
    setIsFormDirty(false);
    if (returnToWindow) {
      setSelectedViolation(returnToWindow);
      setReturnToWindow(null);
    }
  };

  const filters = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      conditionId,
      importedOnly,
      eventDateFrom: effectiveEventDateFrom,
      eventDateTo: effectiveEventDateTo,
      cazaEn,
      village,
      lastHours,
      sortOrder,
    }),
    [cazaEn, conditionId, effectiveEventDateFrom, effectiveEventDateTo, lastHours, offset, importedOnly, sortOrder, village],
  );

  const { data, isLoading, isError, refetch, isFetching, dataUpdatedAt } =
    useAirViolationsQuery(filters);
  const { data: villages = [], isLoading: areCazasLoading } = useVillagesQuery();
  const cazaOptions = useMemo(() => {
    const options = new Map<string, { label: string; arabic: string | null }>();
    for (const village of villages) {
      const english = village.caza_en?.trim();
      if (!english) continue;
      const arabic = village.caza_ar?.trim() || null;
      options.set(english, {
        label: arabic ? `${english} - ${arabic}` : english,
        arabic,
      });
    }
    return [...options.entries()]
      .map(([value, option]) => ({ value, ...option }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [villages]);
  const totalFilters = {
    importedOnly,
    limit: 1,
    offset: 0,
    eventDateFrom: effectiveEventDateFrom,
    eventDateTo: effectiveEventDateTo,
    cazaEn,
    village,
    lastHours,
  };
  const summary = useAirViolationSummaryQuery(totalFilters);
  // Show when the page data was successfully refreshed, not the age of the
  // newest incident. A quiet news period must not look like polling stopped.
  const lastRefreshAt = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : null;
  useLiveQueryTitleAddon(lastRefreshAt, isFetching);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const exactAirRows = data?.items ?? [];
  const tableRows = useMemo<AirViolation[]>(
    () => [...exactAirRows].sort((left, right) => {
      const leftDate = `${left.event_date}T${left.event_time ?? "00:00:00"}`;
      const rightDate = `${right.event_date}T${right.event_time ?? "00:00:00"}`;
      const comparison = new Date(rightDate).getTime() - new Date(leftDate).getTime();
      return sortOrder === "oldest" ? -comparison : comparison;
    }),
    [exactAirRows, sortOrder],
  );
  const isLockedByAnother = Boolean(
    selectedViolation?.locked_by_user_id
      && selectedViolation.locked_by_user_id !== currentUserId
      && selectedViolation.edit_lock_expires_at
      && new Date(selectedViolation.edit_lock_expires_at).getTime() > Date.now(),
  );
  const selectedWindowVillages = useMemo(
    () => displayVillages(selectedViolation),
    [selectedViolation],
  );

  const openReportEditor = async (airViolationId: number, parentWindow: AirViolation | null = null) => {
    setActionError("");
    try {
      const locked = await acquireAirViolationEditLock(airViolationId);
      setReturnToWindow(parentWindow);
      setEditingViolation(locked);
      setSelectedViolation(null);
      setCreateError("");
      setIsFormDirty(false);
      setIsCreateOpen(true);
      await refetch();
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        setActionError("This report is currently being edited by another administrator.");
        await refetch();
      } else {
        setActionError("Could not open this report for editing. Please try again.");
      }
    }
  };

  // Keep an open details dialog synchronized with the live-polled list. Without
  // this, corrected OCR/news text remains stale until the dialog is reopened.
  useEffect(() => {
    if (!selectedViolation) {
      return;
    }
    const refreshed = exactAirRows.find((row) => row.id === selectedViolation.id);
    if (refreshed) {
      setSelectedViolation(refreshed);
    }
  }, [exactAirRows, selectedViolation?.id]);

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

  const updateTimeWindow = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("last_hours", value);
    else next.delete("last_hours");
    next.delete("event_date_from");
    next.delete("event_date_to");
    next.delete("page");
    setParams(next);
  };

  const updateDateParam = (key: "event_date_from" | "event_date_to", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (value) {
      next.delete("last_hours");
      setCustomHoursMode(false);
    }
    next.delete("page");
    setParams(next);
  };

  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    if (nextPage <= 1) {
      next.delete("page");
    } else {
      next.set("page", encodePageParam(nextPage));
    }
    setParams(next);
  };

  const columns: Array<DataTableColumn<AirViolation>> = [
    {
      key: "activity",
      header: "Activity",
      className: "w-[15rem] min-w-[15rem]",
      render: (row) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex min-w-7 items-center justify-center rounded-full bg-accent px-2 py-0.5 text-caption font-semibold text-white">
              {offset + tableRows.indexOf(row) + 1}
            </span>
            <span className="font-semibold text-text-primary">{row.action_en}</span>
            {windowRule(row) ? (
              <span className="rounded-full bg-surface-muted px-2 py-0.5 text-caption font-semibold text-text-muted">
                {windowRule(row)}
              </span>
            ) : null}
          </div>
          <p className="text-small text-text-muted">{row.caza_en || row.caza_ar || emptyText}</p>
          <Button type="button" variant="secondary" className="h-8 whitespace-nowrap" onClick={() => { setActionError(""); setSelectedViolation(row); }}>
            View details
          </Button>
        </div>
      ),
      sortValue: (row) => `${row.action_en} ${row.caza_en ?? ""}`,
    },
    {
      key: "coverage",
      header: "Coverage",
      className: "w-[20rem] min-w-[20rem]",
      render: (row) => {
        const villages = displayVillages(row);
        const visibleVillages = villages.slice(0, 3);
        const hiddenCount = Math.max(0, villages.length - visibleVillages.length);
        const reportCount = row.window_violation_count ?? 1;
        return (
          <div className="space-y-2 whitespace-normal">
            <p className="text-small font-semibold text-text-primary">
              {reportCount} {reportCount === 1 ? "report" : "reports"} · {villages.length} {villages.length === 1 ? "village" : "villages"}
            </p>
            <div className="flex flex-wrap gap-1">
              {visibleVillages.map((village) => (
                <span key={village.village_id ?? `name:${village.name}`} className="rounded border border-border bg-surface px-2 py-0.5 text-caption text-text-primary">{village.name}</span>
              ))}
              {hiddenCount ? <span className="rounded bg-surface-muted px-2 py-0.5 text-caption font-semibold text-text-muted">+{hiddenCount} more</span> : null}
              {!villages.length ? <span className="text-text-muted">{emptyText}</span> : null}
            </div>
          </div>
        );
      },
      sortValue: (row) => displayVillages(row).map((village) => village.name).join(", "),
    },
    {
      key: "updated",
      header: "Latest update",
      className: "w-[14rem] min-w-[14rem]",
      render: (row) => row.import_enrichment?.date_source === "fallback" ? (
        <span>Date unavailable</span>
      ) : (
        <div className="space-y-1 whitespace-normal">
          <p className="font-medium text-text-primary">{formatDate(row.event_date)} · {formatTime(row.event_time)}</p>
          {compactWindowRange(row) ? <p className="text-small text-text-muted">Activity: {compactWindowRange(row)}</p> : <p className="text-small text-text-muted">Individual report</p>}
        </div>
      ),
      sortValue: (row) => row.window_start ?? row.window_id ?? "",
    },
  ];

  return (
    <div className="space-y-5">
      <div className="flex gap-2" aria-label="Record views">
        <Button type="button" variant={importedOnly ? "secondary" : "primary"} aria-pressed={!importedOnly} onClick={() => updateParam("imported_only", "")}>All records</Button>
        <Button type="button" variant={importedOnly ? "primary" : "secondary"} aria-pressed={importedOnly} onClick={() => updateParam("imported_only", "true")}>Imported</Button>
      </div>
      <div className="rounded-lg border border-border bg-surface-raised p-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="air-caza-filter">Caza</Label>
            <Select
              id="air-caza-filter"
              value={cazaEn}
              onChange={(value) => updateParam("caza_en", value)}
              disabled={areCazasLoading}
              placeholder={areCazasLoading ? "Loading cazas..." : "All cazas"}
              options={cazaOptions}
              searchable
              searchPlaceholder="Search caza in English or Arabic"
              panelClassName="min-w-[22rem]"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-village-filter">Village</Label>
            <Select
              id="air-village-filter"
              value={village}
              onChange={(value) => updateParam("village", value)}
              disabled={areCazasLoading && villages.length === 0}
              placeholder={areCazasLoading && villages.length === 0 ? "Loading villages..." : "All villages"}
              options={villages}
              searchable
              searchPlaceholder="Search village in English or Arabic"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-condition-filter">Action</Label>
            <select
              id="air-condition-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={conditionId}
              onChange={(event) => updateParam("condition_id", event.target.value)}
            ><option value="">All actions</option><option value="35">Warplane — طيران حربي</option><option value="36">Surveillance aircraft — طيران استطلاعي</option><option value="38">Helicopter hovering — طيران مروحي</option><option value="34">Spy balloon — منطاد تجسسي</option></select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-hours-filter">Time range</Label>
            <select
              id="air-hours-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={customHoursMode ? "custom" : lastHours}
              onChange={(event) => {
                const value = event.target.value;
                const custom = value === "custom";
                setCustomHoursMode(custom);
                updateTimeWindow(custom ? "24" : value);
              }}
            >
              <option value="">Any time</option>
              <option value="1">Last 1 hour</option>
              <option value="6">Last 6 hours</option>
              <option value="12">Last 12 hours</option>
              <option value="24">Last 24 hours</option>
              <option value="48">Last 48 hours</option>
              <option value="72">Last 72 hours</option>
              <option value="168">Last 7 days</option>
              <option value="custom">Custom hours</option>
            </select>
            {customHoursMode ? (
              <Input
                aria-label="Custom number of hours"
                type="number"
                min="1"
                max="8760"
                value={lastHours}
                onChange={(event) => updateTimeWindow(event.target.value)}
              />
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-from-filter">From</Label>
            <Input
              id="air-from-filter"
              type="date"
              value={effectiveEventDateFrom}
              max={effectiveEventDateTo || undefined}
              onChange={(event) => updateDateParam("event_date_from", event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-to-filter">To</Label>
            <Input
              id="air-to-filter"
              type="date"
              value={effectiveEventDateTo}
              min={effectiveEventDateFrom || undefined}
              onChange={(event) => updateDateParam("event_date_to", event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-sort-order">News order</Label>
            <Select
              id="air-sort-order"
              value={sortOrder}
              placeholder="Latest news first"
              options={[
                { value: "newest", label: "Latest news first" },
                { value: "oldest", label: "First news first" },
              ]}
              onChange={(value) => updateParam("sort_order", value === "newest" ? "" : value)}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Air violation totals">
          <div className="rounded-lg border border-border bg-surface-raised px-5 py-4">
            <p className="text-caption font-semibold uppercase text-text-muted">Total warplanes</p>
            <p className="mt-2 text-h3 font-semibold tabular-nums text-text-primary" aria-live="polite">
              {summary.isLoading ? "Loading…" : summary.data?.warplanes ?? 0}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-surface-raised px-5 py-4">
            <p className="text-caption font-semibold uppercase text-text-muted">Total surveillance aircraft</p>
            <p className="mt-2 text-h3 font-semibold tabular-nums text-text-primary" aria-live="polite">
              {summary.isLoading ? "Loading…" : summary.data?.surveillance_aircraft ?? 0}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-surface-raised px-5 py-4">
            <p className="text-caption font-semibold uppercase text-text-muted">Total helicopter hovering</p>
            <p className="mt-2 text-h3 font-semibold tabular-nums text-text-primary" aria-live="polite">
              {summary.isLoading ? "Loading…" : summary.data?.helicopters ?? 0}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-surface-raised px-5 py-4">
            <p className="text-caption font-semibold uppercase text-text-muted">Total spy balloons</p>
            <p className="mt-2 text-h3 font-semibold tabular-nums text-text-primary" aria-live="polite">
              {summary.isLoading ? "Loading…" : summary.data?.spy_balloons ?? 0}
            </p>
          </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 rounded-lg border border-border bg-surface-raised p-4">
          <Button type="button" variant="secondary" onClick={() => { setImportError(""); setImportResult(null); setIsImportOpen(true); }}>
            Import Khabar
          </Button>
          <Button type="button" variant="secondary" isLoading={isExporting} loadingText="Exporting" onClick={async () => { setIsExporting(true); setImportMessage(""); try { await exportAirViolations(); } catch { setImportMessage("Export failed. Check the API connection and try again."); } finally { setIsExporting(false); } }}>
            Export Excel
          </Button>
          <Button type="button" onClick={() => { setEditingViolation(null); setIsFormDirty(false); setCreateError(""); setIsCreateOpen(true); }}>
            Create
          </Button>
          {hasFilters ? (
            <Button type="button" variant="ghost" className="h-9" onClick={() => { setCustomHoursMode(false); setParams({}); }}>
              Clear filters
            </Button>
          ) : null}
          {importMessage ? <p className="text-small text-text-muted">{importMessage}</p> : null}
      </div>

      {isImportOpen ? (
        <Dialog title="Import Khabar" onClose={() => { if (!isImporting) setIsImportOpen(false); }}>
          <form className="space-y-4" onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const file = form.get("file");
            if (!(file instanceof File) || !file.size) return;
            setIsImporting(true);
            setImportError("");
            setImportResult(null);
            try {
              const result = await importAirViolationKhabar(file, String(form.get("default_date")));
              setImportResult(result);
              if (result.succeeded) {
                setParams({});
                setCustomHoursMode(false);
                await Promise.all([refetch(), summary.refetch()]);
              }
            } catch (error) {
              const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
              const validationErrors = Array.isArray(detail)
                ? detail.map((item: { loc?: string[]; msg?: string }) => `${item.loc?.slice(1).join(".") || "File"}: ${item.msg || "Invalid value"}`).join(" ")
                : null;
              setImportError(typeof detail === "string" ? detail : validationErrors || (
                axios.isAxiosError(error) && !error.response
                  ? "The connection was interrupted. The server may still be importing. Check the records before retrying."
                  : "The server could not complete the import. Check the records before retrying."
              ));
            } finally { setIsImporting(false); }
          }}>
            <div><Label htmlFor="khabar-file">Data file</Label><Input id="khabar-file" name="file" type="file" accept=".xlsx,.json,.geojson" required disabled={isImporting} /></div>
            <div><Label htmlFor="khabar-date">Date for records without a date</Label><Input id="khabar-date" name="default_date" type="date" defaultValue={getBeirutDate()} required disabled={isImporting} /></div>
            {importError ? <p role="alert" className="text-small text-danger">{importError}</p> : null}
            {importResult ? <div role="status" className="space-y-2 text-small">
              <p>{importResult.succeeded} imported, {importResult.skipped ?? 0} already imported, {importResult.failed} failed.</p>
              {importResult.succeeded + (importResult.skipped ?? 0) > 0 ? <Button type="button" variant="secondary" onClick={() => { setParams({ imported_only: "true" }); setCustomHoursMode(false); setIsImportOpen(false); }}>View imported records</Button> : null}
              <ul className="max-h-48 overflow-auto">{importResult.row_errors.map((error) => <li key={error.row}>Row {error.row}: {error.error}</li>)}</ul>
            </div> : null}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={isImporting} onClick={() => setIsImportOpen(false)}>Close</Button>
              <Button type="submit" isLoading={isImporting} loadingText="Importing">Import and classify</Button>
            </div>
          </form>
        </Dialog>
      ) : null}

      <DataTable
        columns={columns}
        rows={tableRows}
        getRowKey={(row) => `air-${row.window_id ?? row.id}`}
        loading={isLoading}
        error={isError}
        minWidth="680px"
        clientSort={false}
        emptyState={
          <EmptyState
            title={hasFilters ? "No matching air violations" : "No air violations recorded yet"}
            description={
              hasFilters
                ? "Adjust or clear the filters to broaden the results."
                : "Airspace violation records will appear here once routing starts writing them."
            }
          />
        }
        errorState={
          <EmptyState
            title="Could not load air violations"
            description="The air violations list could not be loaded. Please try again."
          />
        }
      />

      {selectedViolation ? (
        <Dialog
          title={`${selectedViolation.action_en} · ${selectedViolation.caza_en || selectedViolation.caza_ar || "Unknown area"}`}
          eyebrow={isWindowedActivity(selectedViolation) ? (selectedViolation.condition_id === 35 ? "Warplane activity window" : "Surveillance activity window") : "Air violation report"}
          onClose={() => { if (!confirmDelete) setSelectedViolation(null); }}
          size="xl"
        >
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {selectedViolation.is_imported ? <>
              <div><dt className="text-caption font-semibold uppercase text-text-muted">Imported on</dt><dd className="mt-1">{new Date(selectedViolation.created_at).toLocaleString()}</dd></div>
              {selectedViolation.import_filename ? <div><dt className="text-caption font-semibold uppercase text-text-muted">File</dt><dd className="mt-1">{selectedViolation.import_filename}</dd></div> : null}
            </> : null}
            <div className="rounded-md border border-border bg-surface p-3"><dt className="text-caption font-semibold uppercase text-text-muted">Reports</dt><dd className="mt-1 text-h4 font-semibold">{selectedViolation.window_violation_count ?? 1}</dd></div>
            <div className="rounded-md border border-border bg-surface p-3"><dt className="text-caption font-semibold uppercase text-text-muted">Villages</dt><dd className="mt-1 text-h4 font-semibold">{selectedWindowVillages.length}</dd></div>
            {isPerReportBreach(selectedViolation) ? <div className="rounded-md border border-border bg-surface p-3"><dt className="text-caption font-semibold uppercase text-text-muted">Breaches</dt><dd className="mt-1 text-h4 font-semibold">{selectedViolation.breach_count ?? 1} <span className="text-small font-normal text-text-muted">({breachUnitLabel(selectedViolation)})</span></dd></div> : null}
            <div className="rounded-md border border-border bg-surface p-3"><dt className="text-caption font-semibold uppercase text-text-muted">Rule</dt><dd className="mt-1 font-semibold">{windowRule(selectedViolation) ?? (isPerReportBreach(selectedViolation) ? "Every report counts" : "Individual event")}</dd></div>
            <div className="rounded-md border border-border bg-surface p-3"><dt className="text-caption font-semibold uppercase text-text-muted">Activity time</dt><dd className="mt-1 text-small font-semibold">{compactWindowRange(selectedViolation) ?? `${formatDate(selectedViolation.event_date)} · ${formatTime(selectedViolation.event_time)}`}</dd></div>
            <div className="sm:col-span-2 lg:col-span-4">
              <dt className="text-caption font-semibold uppercase text-text-muted">{isWindowedActivity(selectedViolation) ? "Villages in this window" : "Villages in this report"}</dt>
              <dd className="mt-2 flex flex-wrap gap-1.5">
                {selectedWindowVillages.length ? selectedWindowVillages.map((village) => (
                  <span key={village.village_id ?? `name:${village.name}`} className="rounded border border-border bg-surface px-2 py-0.5 text-caption leading-5 text-text-primary">
                    {village.name}
                  </span>
                )) : emptyText}
              </dd>
            </div>
            <div className="sm:col-span-2"><dt className="text-caption font-semibold uppercase text-text-muted">Action (Arabic)</dt><dd className="mt-1 text-right" dir="rtl" lang="ar">{selectedViolation.action_ar}</dd></div>
            {selectedViolation.window_reports?.length <= 1 ? <div className="sm:col-span-2"><dt className="text-caption font-semibold uppercase text-text-muted">Original source</dt><dd className="mt-1">{selectedViolation.source_name}</dd></div> : null}
          </dl>
          {selectedViolation.window_reports?.length > 1 ? (
            <section className="mt-5">
              <h3 className="text-caption font-semibold uppercase text-text-muted">
                Reports in this window ({selectedViolation.window_reports.length})
              </h3>
              <div className="mt-3 space-y-3">
                {selectedViolation.window_reports.map((report) => (
                  <article key={report.id} className="rounded-md border border-border bg-surface p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-small text-text-muted">
                      <span>{formatDate(report.event_date)} at {formatTime(report.event_time)}</span>
                      <span>{report.source_name}</span>
                    </div>
                    {report.villages.length ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {report.villages.map((village) => (
                          <span key={village.village_id ?? `name:${village.name}`} className="rounded border border-border px-1.5 py-0.5 text-caption">{village.name}</span>
                        ))}
                      </div>
                    ) : null}
                    <p className="mt-3 whitespace-pre-wrap text-body text-text-primary" dir="auto">{report.khabar}</p>
                    {report.source_link ? (
                      <a href={report.source_link} target="_blank" rel="noreferrer" className="mt-2 inline-block text-small font-semibold text-accent hover:underline">
                        Open source
                      </a>
                    ) : null}
                    <div className="mt-3 flex justify-end border-t border-border pt-3">
                      <Button type="button" variant="secondary" className="h-8" onClick={() => void openReportEditor(report.id, selectedViolation)}>
                        Update this report
                      </Button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ) : (
            <div className="mt-5 rounded-md border border-border bg-surface p-4">
              <p className="text-caption font-semibold uppercase text-text-muted">News</p>
              <p className="mt-2 whitespace-pre-wrap text-body text-text-primary" dir="auto">{selectedViolation.khabar}</p>
            </div>
          )}
          <dl className="mt-5 grid gap-5 sm:grid-cols-2">
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Note 1</dt><dd className="mt-1 whitespace-pre-wrap">{selectedViolation.note_1 || emptyText}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Note 2</dt><dd className="mt-1 whitespace-pre-wrap">{selectedViolation.note_2 || emptyText}</dd></div>
          </dl>
          {selectedViolation.import_enrichment?.reason ? <p className="mt-4 text-small text-text-muted">{selectedViolation.import_enrichment.reason}</p> : null}
          {selectedViolation.import_enrichment?.location_basis ? <p className="mt-4 text-small text-text-muted">{selectedViolation.import_enrichment.location_basis} {selectedViolation.import_enrichment.location_reference ? <a href={selectedViolation.import_enrichment.location_reference} target="_blank" rel="noreferrer" className="underline">Location reference</a> : null}</p> : null}
          {selectedViolation.import_enrichment?.text ? <div className="mt-5"><p className="text-caption font-semibold uppercase text-text-muted">Source post</p><p className="mt-2 whitespace-pre-wrap" dir="auto">{selectedViolation.import_enrichment.text}</p></div> : null}
          {selectedViolation.import_row ? <div className="mt-5">
            <p className="text-caption font-semibold uppercase text-text-muted">Original file data</p>
            <dl className="mt-3 grid gap-4 sm:grid-cols-2">
              {Object.entries(selectedViolation.import_row).filter(([key]) => key).map(([key, value]) => <div key={key}>
                <dt className="text-small font-semibold">{key}</dt>
                <dd className="mt-1 whitespace-pre-wrap break-words" dir="auto">{value == null || value === "" ? emptyText : typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
              </div>)}
            </dl>
          </div> : null}
          {selectedViolation.source_link ? (
            <a className="mt-5 inline-block font-semibold text-accent underline-offset-4 hover:underline" href={selectedViolation.source_link} target="_blank" rel="noreferrer">
              Open original source
            </a>
          ) : null}
          {actionError ? <p className="mt-5 text-small font-medium text-danger" role="alert">{actionError}</p> : null}
          {(selectedViolation.window_reports?.length ?? 0) <= 1 ? <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              disabled={isLockedByAnother}
              onClick={async () => {
                await openReportEditor(selectedViolation.id);
              }}
            >
              {isLockedByAnother ? "Being edited" : "Update"}
            </Button>
            <Button
              type="button"
              variant="destructive"
              isLoading={isDeleting}
              loadingText="Rejecting"
              disabled={isLockedByAnother}
              onClick={async () => {
                setActionError("");
                try {
                  const locked = await acquireAirViolationEditLock(selectedViolation.id);
                  setSelectedViolation(locked);
                  setConfirmDelete(true);
                  await refetch();
                } catch (error) {
                  if (axios.isAxiosError(error) && error.response?.status === 409) {
                    setActionError("This record is currently being edited by another administrator.");
                    await refetch();
                  } else {
                    setActionError("Could not lock this report for rejection. Please try again.");
                  }
                }
              }}
            >
              Reject news
            </Button>
          </div> : (
            <p className="mt-6 border-t border-border pt-4 text-small text-text-muted">
              This activity window contains multiple reports. Update the required report from the list above.
            </p>
          )}
        </Dialog>
      ) : null}

      {confirmDiscard ? (
        <ConfirmDialog
          title="Discard unsaved changes?"
          description="The changes in this form have not been saved and will be lost."
          confirmLabel="Discard changes"
          destructive
          onCancel={() => setConfirmDiscard(false)}
          onConfirm={async () => {
            if (editingViolation) {
              await releaseAirViolationEditLock(editingViolation.id);
              await refetch();
            }
            setConfirmDiscard(false);
            setIsCreateOpen(false);
            setEditingViolation(null);
            setIsFormDirty(false);
            if (returnToWindow) {
              setSelectedViolation(returnToWindow);
              setReturnToWindow(null);
            }
          }}
        />
      ) : null}

      {confirmDelete && selectedViolation ? (
        <ConfirmDialog
          title="Reject this news report?"
          description="The air violation will be removed and its source report will move to Rejected News."
          confirmLabel="Reject news"
          destructive
          isLoading={isDeleting}
          onCancel={async () => {
            setConfirmDelete(false);
            await releaseAirViolationEditLock(selectedViolation.id);
            await refetch();
          }}
          onConfirm={async () => {
            setIsDeleting(true);
            try {
              setActionError("");
              await deleteAirViolation(selectedViolation.id, selectedViolation.version);
              setConfirmDelete(false);
              setSelectedViolation(null);
              await refetch();
            } catch (error) {
              setConfirmDelete(false);
              if (axios.isAxiosError(error) && error.response?.status === 409) {
                setActionError("This record was updated by another administrator. Refresh the page before rejecting it.");
                await refetch();
              } else {
                setActionError("Could not reject the news report. Please try again.");
              }
            } finally {
              setIsDeleting(false);
            }
          }}
        />
      ) : null}

      {isCreateOpen ? (
        <Dialog
          title={editingViolation ? "Update air violation" : "Create air violation"}
          eyebrow={editingViolation ? "Edit record" : "Create record"}
          onClose={() => { if (!confirmDiscard) closeEditor(); }}
          size="lg"
          closeLabel={returnToWindow ? "Back to reports" : "Close"}
        >
          <form
            className="space-y-5"
            onChange={() => setIsFormDirty(true)}
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const selectedCaza = String(form.get("caza_en") ?? "").trim();
              const selectedCazaOption = cazaOptions.find((option) => option.value === selectedCaza);
              setIsCreating(true);
              setCreateError("");
              try {
                const payload = {
                  condition_id: Number(form.get("condition_id")),
                  caza_en: selectedCaza,
                  caza_ar: selectedCazaOption?.arabic ?? editingViolation?.caza_ar ?? null,
                  event_date: String(form.get("event_date") ?? ""),
                  event_time: String(form.get("event_time") ?? "") || null,
                  khabar: String(form.get("khabar") ?? "").trim(),
                  note_1: String(form.get("note_1") ?? "").trim() || null,
                  note_2: String(form.get("note_2") ?? "").trim() || null,
                  source_link: String(form.get("source_link") ?? "").trim() || null,
                };
                if (editingViolation) {
                  await updateAirViolation(editingViolation.id, {
                    ...payload,
                    version: editingViolation.version,
                  });
                }
                else await createAirViolation(payload);
                setIsCreateOpen(false);
                setEditingViolation(null);
                setIsFormDirty(false);
                await refetch();
                if (returnToWindow) {
                  setSelectedViolation(returnToWindow);
                  setReturnToWindow(null);
                }
              } catch (error) {
                if (axios.isAxiosError(error) && error.response?.status === 409) {
                  setCreateError("This record was updated by another administrator. Close this form, review the latest record, and apply your changes again.");
                  await refetch();
                } else {
                  setCreateError(editingViolation
                    ? "Could not update the air violation. Check the required fields and try again."
                    : "Could not create the air violation. Check the required fields and try again.");
                }
              } finally {
                setIsCreating(false);
              }
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2"><Label htmlFor="create-caza">District (Caza) *</Label><Select id="create-caza" name="caza_en" required defaultValue={editingViolation?.caza_en ?? ""} placeholder={areCazasLoading ? "Loading cazas..." : "Select a caza"} options={cazaOptions} disabled={areCazasLoading} searchable searchPlaceholder="Search caza in English or Arabic" className="mt-2" /></div>
              <div className="sm:col-span-2"><Label htmlFor="create-condition">Action *</Label><select id="create-condition" name="condition_id" required defaultValue={editingViolation?.condition_id ?? 35} className="mt-2 h-11 w-full rounded-md border border-input-border bg-input-bg px-3"><option value="35">Warplane — طيران حربي</option><option value="36">Surveillance aircraft — طيران استطلاعي</option><option value="38">Helicopter hovering — طيران مروحي</option><option value="34">Spy balloon — منطاد تجسسي</option></select></div>
              <div><Label htmlFor="create-date">Date *</Label><Input id="create-date" name="event_date" type="date" required className="mt-2" defaultValue={editingViolation?.event_date ?? getBeirutDate()} /></div>
              <div><Label htmlFor="create-time">Time (optional)</Label><Input id="create-time" name="event_time" type="time" className="mt-2" defaultValue={editingViolation?.event_time?.slice(0, 5) ?? ""} /></div>
            </div>
            <div><Label htmlFor="create-news">News text *</Label><textarea id="create-news" name="khabar" required rows={5} dir="auto" placeholder="Enter the complete news report" defaultValue={editingViolation?.khabar ?? ""} className="mt-2 w-full rounded-md border border-input-border bg-input-bg px-3 py-2 text-body" /></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><Label htmlFor="create-note-1">Note 1 (optional)</Label><Input id="create-note-1" name="note_1" placeholder="Add note 1" className="mt-2" defaultValue={editingViolation?.note_1 ?? ""} /></div>
              <div><Label htmlFor="create-note-2">Note 2 (optional)</Label><Input id="create-note-2" name="note_2" placeholder="Add note 2" className="mt-2" defaultValue={editingViolation?.note_2 ?? ""} /></div>
            </div>
            <div><Label htmlFor="create-link">Source link (optional)</Label><Input id="create-link" name="source_link" type="url" placeholder="https://..." className="mt-2" defaultValue={editingViolation?.source_link ?? ""} /></div>
            {createError ? <p className="text-small font-medium text-danger" role="alert">{createError}</p> : null}
            <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-border bg-surface-raised px-6 py-4"><Button type="button" variant="secondary" onClick={closeEditor}>{returnToWindow ? "Back to all reports" : "Cancel"}</Button><Button type="submit" isLoading={isCreating} loadingText={editingViolation ? "Updating" : "Creating"}>{editingViolation ? "Update" : "Create"}</Button></div>
          </form>
        </Dialog>
      ) : null}

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

