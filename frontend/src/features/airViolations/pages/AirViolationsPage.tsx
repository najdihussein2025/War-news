import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, DataTable, Dialog, EmptyState, Input, Label, type DataTableColumn } from "../../../components/ui";
import { formatDate } from "../../../lib/formatters";
import { useAirViolationsQuery } from "../hooks";
import { exportAirViolations } from "../api";
import type { AirViolation } from "../types";

const PAGE_SIZE = 25;

const emptyText = "—";

const formatTime = (value: string | null) => {
  if (!value) {
    return emptyText;
  }
  return value.slice(0, 5);
};

const TextCell = ({ value }: { value: string | null }) => (
  <span className="block max-w-sm whitespace-pre-wrap text-text-primary">
    {value || emptyText}
  </span>
);

export const AirViolationsPage = () => {
  const [importMessage, setImportMessage] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [selectedViolation, setSelectedViolation] = useState<AirViolation | null>(null);
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const offset = (page - 1) * PAGE_SIZE;
  const conditionId = params.get("condition_id") ?? "";
  const eventDateFrom = params.get("event_date_from") ?? "";
  const eventDateTo = params.get("event_date_to") ?? "";
  const cazaEn = params.get("caza_en") ?? "";
  const hasFilters = Boolean(conditionId || eventDateFrom || eventDateTo || cazaEn);

  const filters = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      conditionId,
      eventDateFrom,
      eventDateTo,
      cazaEn,
    }),
    [cazaEn, conditionId, eventDateFrom, eventDateTo, offset],
  );

  const { data, isLoading, isError } = useAirViolationsQuery(filters);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rows = data?.items ?? [];

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

  const columns: Array<DataTableColumn<AirViolation>> = [
    {
      key: "caza",
      header: "Caza",
      render: (row) => <span className="font-semibold text-text-primary">{row.caza_en || row.caza_ar || emptyText}</span>,
      sortValue: (row) => row.caza_en ?? row.caza_ar ?? "",
    },
    {
      key: "action-en",
      header: "Action",
      render: (row) => <TextCell value={row.action_en} />,
      sortValue: (row) => row.action_en,
    },
    {
      key: "news",
      header: "News",
      render: (row) => {
        const news = row.khabar.replace(/\s+/g, " ").trim();
        return <span className="block max-w-md text-text-primary">{news.length > 110 ? `${news.slice(0, 110)}…` : news}</span>;
      },
      sortValue: (row) => row.khabar,
    },
    {
      key: "date",
      header: "Date / Time",
      render: (row) => `${formatDate(row.event_date)} · ${formatTime(row.event_time)}`,
      sortValue: (row) => new Date(row.event_date).getTime(),
    },
    {
      key: "details",
      header: "Details",
      className: "w-32",
      render: (row) => (
        <Button type="button" variant="secondary" className="h-9 whitespace-nowrap" onClick={() => setSelectedViolation(row)}>
          View details
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-border bg-surface-raised p-4">
        <div className="grid gap-4 lg:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="air-caza-filter">Caza</Label>
            <Input
              id="air-caza-filter"
              value={cazaEn}
              onChange={(event) => updateParam("caza_en", event.target.value)}
              placeholder="Search caza"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-condition-filter">Condition</Label>
            <select
              id="air-condition-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={conditionId}
              onChange={(event) => updateParam("condition_id", event.target.value)}
            ><option value="">All conditions</option><option value="35">35</option><option value="36">36</option><option value="38">38</option></select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-from-filter">From</Label>
            <Input
              id="air-from-filter"
              type="date"
              value={eventDateFrom}
              onChange={(event) => updateParam("event_date_from", event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="air-to-filter">To</Label>
            <Input
              id="air-to-filter"
              type="date"
              value={eventDateTo}
              onChange={(event) => updateParam("event_date_to", event.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button type="button" variant="secondary" isLoading={isExporting} loadingText="Exporting" onClick={async () => { setIsExporting(true); setImportMessage(""); try { await exportAirViolations(); } catch { setImportMessage("Export failed. Check the API connection and try again."); } finally { setIsExporting(false); } }}>
            Export Excel
          </Button>
          {hasFilters ? (
            <Button type="button" variant="ghost" className="h-9" onClick={() => setParams({})}>
              Clear filters
            </Button>
          ) : null}
          {importMessage ? <p className="text-small text-text-muted">{importMessage}</p> : null}
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(row) => String(row.id)}
        loading={isLoading}
        error={isError}
        minWidth="100%"
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
          title={`Air violation #${selectedViolation.id}`}
          onClose={() => setSelectedViolation(null)}
          size="lg"
        >
          <dl className="grid gap-5 sm:grid-cols-2">
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Caza</dt><dd className="mt-1">{selectedViolation.caza_en || selectedViolation.caza_ar || emptyText}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Month</dt><dd className="mt-1">{selectedViolation.event_month || emptyText}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Action (English)</dt><dd className="mt-1">{selectedViolation.action_en}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Action (Arabic)</dt><dd className="mt-1 text-right" dir="rtl" lang="ar">{selectedViolation.action_ar}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Original source</dt><dd className="mt-1">{selectedViolation.source_name}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Date and time</dt><dd className="mt-1">{formatDate(selectedViolation.event_date)} at {formatTime(selectedViolation.event_time)}</dd></div>
          </dl>
          <div className="mt-5 rounded-md border border-border bg-surface p-4">
            <p className="text-caption font-semibold uppercase text-text-muted">News</p>
            <p className="mt-2 whitespace-pre-wrap text-body text-text-primary" dir="auto">{selectedViolation.khabar}</p>
          </div>
          <dl className="mt-5 grid gap-5 sm:grid-cols-2">
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Note 1</dt><dd className="mt-1 whitespace-pre-wrap">{selectedViolation.note_1 || emptyText}</dd></div>
            <div><dt className="text-caption font-semibold uppercase text-text-muted">Note 2</dt><dd className="mt-1 whitespace-pre-wrap">{selectedViolation.note_2 || emptyText}</dd></div>
          </dl>
          {selectedViolation.source_link ? (
            <a className="mt-5 inline-block font-semibold text-accent underline-offset-4 hover:underline" href={selectedViolation.source_link} target="_blank" rel="noreferrer">
              Open original source
            </a>
          ) : null}
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
