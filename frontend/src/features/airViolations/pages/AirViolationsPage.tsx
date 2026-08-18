import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, ConfirmDialog, DataTable, Dialog, EmptyState, Input, Label, type DataTableColumn } from "../../../components/ui";
import { formatDate } from "../../../lib/formatters";
import { getBeirutDate } from "../../../lib/localDate";
import { useAirViolationsQuery } from "../hooks";
import { createAirViolation, deleteAirViolation, exportAirViolations, updateAirViolation } from "../api";
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
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingViolation, setEditingViolation] = useState<AirViolation | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isFormDirty, setIsFormDirty] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [createError, setCreateError] = useState("");
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const offset = (page - 1) * PAGE_SIZE;
  const conditionId = params.get("condition_id") ?? "";
  const eventDateFrom = params.get("event_date_from") ?? "";
  const eventDateTo = params.get("event_date_to") ?? "";
  const cazaEn = params.get("caza_en") ?? "";
  const hasFilters = Boolean(conditionId || eventDateFrom || eventDateTo || cazaEn);
  const closeEditor = () => {
    if (isFormDirty) {
      setConfirmDiscard(true);
      return;
    }
    setIsCreateOpen(false);
    setEditingViolation(null);
    setIsFormDirty(false);
  };

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
      key: "number",
      header: "#",
      className: "w-14 tabular-nums text-text-muted",
      render: (row) => offset + rows.indexOf(row) + 1,
    },
    {
      key: "caza",
      header: "Caza",
      render: (row) => <span className="font-semibold text-text-primary">{row.caza_en || row.caza_ar || emptyText}</span>,
      sortValue: (row) => row.caza_en ?? row.caza_ar ?? "",
    },
    {
      key: "action-en",
      header: "Action",
      render: (row) => (
        <div>
          <TextCell value={row.action_en} />
          <span className="mt-1 block text-right text-text-muted" dir="rtl" lang="ar">{row.action_ar}</span>
        </div>
      ),
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
            <Label htmlFor="air-condition-filter">Action</Label>
            <select
              id="air-condition-filter"
              className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary"
              value={conditionId}
              onChange={(event) => updateParam("condition_id", event.target.value)}
            ><option value="">All actions</option><option value="35">Warplane — طيران حربي</option><option value="36">Surveillance aircraft — طيران استطلاعي</option><option value="38">Helicopter hovering — طيران مروحي</option></select>
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
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          <Button type="button" variant="secondary" isLoading={isExporting} loadingText="Exporting" onClick={async () => { setIsExporting(true); setImportMessage(""); try { await exportAirViolations(); } catch { setImportMessage("Export failed. Check the API connection and try again."); } finally { setIsExporting(false); } }}>
            Export Excel
          </Button>
          <Button type="button" onClick={() => { setEditingViolation(null); setIsFormDirty(false); setCreateError(""); setIsCreateOpen(true); }}>
            Create
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
          title="Air violation"
          onClose={() => { if (!confirmDelete) setSelectedViolation(null); }}
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
          <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setEditingViolation(selectedViolation);
                setSelectedViolation(null);
                setCreateError("");
                setIsFormDirty(false);
                setIsCreateOpen(true);
              }}
            >
              Update
            </Button>
            <Button
              type="button"
              variant="destructive"
              isLoading={isDeleting}
              loadingText="Deleting"
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </Button>
          </div>
        </Dialog>
      ) : null}

      {confirmDiscard ? (
        <ConfirmDialog
          title="Discard unsaved changes?"
          description="The changes in this form have not been saved and will be lost."
          confirmLabel="Discard changes"
          destructive
          onCancel={() => setConfirmDiscard(false)}
          onConfirm={() => {
            setConfirmDiscard(false);
            setIsCreateOpen(false);
            setEditingViolation(null);
            setIsFormDirty(false);
          }}
        />
      ) : null}

      {confirmDelete && selectedViolation ? (
        <ConfirmDialog
          title="Delete air violation?"
          description="This record will be permanently deleted. This action cannot be undone."
          confirmLabel="Delete record"
          destructive
          isLoading={isDeleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={async () => {
            setIsDeleting(true);
            try {
              await deleteAirViolation(selectedViolation.id);
              setConfirmDelete(false);
              setSelectedViolation(null);
              await refetch();
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
        >
          <form
            className="space-y-5"
            onChange={() => setIsFormDirty(true)}
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              setIsCreating(true);
              setCreateError("");
              try {
                const payload = {
                  condition_id: Number(form.get("condition_id")),
                  caza_en: String(form.get("caza_en") ?? "").trim(),
                  caza_ar: String(form.get("caza_ar") ?? "").trim() || null,
                  event_date: String(form.get("event_date") ?? ""),
                  event_time: String(form.get("event_time") ?? "") || null,
                  khabar: String(form.get("khabar") ?? "").trim(),
                  note_1: String(form.get("note_1") ?? "").trim() || null,
                  note_2: String(form.get("note_2") ?? "").trim() || null,
                  source_link: String(form.get("source_link") ?? "").trim() || null,
                };
                if (editingViolation) await updateAirViolation(editingViolation.id, payload);
                else await createAirViolation(payload);
                setIsCreateOpen(false);
                setEditingViolation(null);
                setIsFormDirty(false);
                await refetch();
              } catch {
                setCreateError("Could not create the air violation. Check the required fields and try again.");
              } finally {
                setIsCreating(false);
              }
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div><Label htmlFor="create-caza">District (Caza) *</Label><Input id="create-caza" name="caza_en" required placeholder="e.g. Sour" className="mt-2" defaultValue={editingViolation?.caza_en ?? ""} /></div>
              <div><Label htmlFor="create-caza-ar">District in Arabic (optional)</Label><Input id="create-caza-ar" name="caza_ar" dir="rtl" placeholder="مثال: صور" className="mt-2" defaultValue={editingViolation?.caza_ar ?? ""} /></div>
              <div className="sm:col-span-2"><Label htmlFor="create-condition">Action *</Label><select id="create-condition" name="condition_id" required defaultValue={editingViolation?.condition_id ?? 35} className="mt-2 h-11 w-full rounded-md border border-input-border bg-input-bg px-3"><option value="35">Warplane — طيران حربي</option><option value="36">Surveillance aircraft — طيران استطلاعي</option><option value="38">Helicopter hovering — طيران مروحي</option></select></div>
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
            <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-border bg-surface-raised px-6 py-4"><Button type="button" variant="secondary" onClick={closeEditor}>Cancel</Button><Button type="submit" isLoading={isCreating} loadingText={editingViolation ? "Updating" : "Creating"}>{editingViolation ? "Update" : "Create"}</Button></div>
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
