import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, DataTable, EmptyState, Input, Label, type DataTableColumn } from "../../../components/ui";
import { formatDate } from "../../../lib/formatters";
import { useAirViolationsQuery } from "../hooks";
import { exportAirViolations, importAirViolations } from "../api";
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [importMessage, setImportMessage] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
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

  const { data, isLoading, isError, refetch } = useAirViolationsQuery(filters);
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
      key: "month",
      header: "Month",
      render: (row) => row.event_month || emptyText,
      sortValue: (row) => row.event_month ?? "",
    },
    {
      key: "action-en",
      header: "Action_E",
      render: (row) => <TextCell value={row.action_en} />,
      sortValue: (row) => row.action_en,
    },
    {
      key: "action-ar",
      header: "Action_A",
      render: (row) => <span className="block max-w-sm whitespace-pre-wrap text-right text-text-primary" dir="rtl" lang="ar">{row.action_ar || emptyText}</span>,
      sortValue: (row) => row.action_ar,
    },
    {
      key: "khabar",
      header: "Khabar",
      render: (row) => <TextCell value={row.khabar} />,
      sortValue: (row) => row.khabar,
    },
    {
      key: "source",
      header: "Source",
      render: (row) => row.source_name,
      sortValue: (row) => row.source_name,
    },
    {
      key: "time",
      header: "Time",
      render: (row) => formatTime(row.event_time),
      sortValue: (row) => row.event_time ?? "",
    },
    {
      key: "date",
      header: "Date",
      render: (row) => formatDate(row.event_date),
      sortValue: (row) => new Date(row.event_date).getTime(),
    },
    {
      key: "note-1",
      header: "Note 1",
      render: (row) => <TextCell value={row.note_1} />,
      sortValue: (row) => row.note_1 ?? "",
    },
    {
      key: "note-2",
      header: "Note 2",
      render: (row) => <TextCell value={row.note_2} />,
      sortValue: (row) => row.note_2 ?? "",
    },
    {
      key: "link",
      header: "Link",
      render: (row) =>
        row.source_link ? (
          <a
            className="font-semibold text-accent underline-offset-4 hover:underline"
            href={row.source_link}
            target="_blank"
            rel="noreferrer"
          >
            Open
          </a>
        ) : (
          emptyText
        ),
      sortValue: (row) => row.source_link ?? "",
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
            <Label htmlFor="air-condition-filter">Condition ID</Label>
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
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept=".xlsx"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              setIsImporting(true);
              setImportMessage("");
              try {
                const result = await importAirViolations(file);
                setImportMessage(`${result.imported} imported, ${result.skipped} skipped, ${result.failed} failed`);
                await refetch();
              } catch {
                setImportMessage("Import failed. Check that the workbook uses the required template.");
              } finally {
                setIsImporting(false);
                event.target.value = "";
              }
            }}
          />
          <Button type="button" isLoading={isImporting} loadingText="Importing" onClick={() => fileInputRef.current?.click()}>
            Import Excel
          </Button>
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
        minWidth="1320px"
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
