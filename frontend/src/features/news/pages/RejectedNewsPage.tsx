import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ConfirmDialog, DataTable, Dialog, EmptyState, Input, type DataTableColumn } from "../../../components/ui";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDateTime } from "../../../lib/formatters";
import { getRejectedNews, getRejectedNewsById, restoreRejectedNews } from "../api";
import type { RejectedNewsItem } from "../types";

const PAGE_SIZE = 100;

const reasonLabel = (type: RejectedNewsItem["rejection_type"]) => ({
  not_relevant: "Not relevant",
  uncertain: "Uncertain",
  duplicate: "Duplicate",
  rejected: "Rejected",
}[type]);

export const RejectedNewsPage = () => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [restoreItem, setRestoreItem] = useState<RejectedNewsItem | null>(null);
  const offset = (page - 1) * PAGE_SIZE;
  const list = useQuery({
    queryKey: ["rejected-news", PAGE_SIZE, offset, search],
    queryFn: () => getRejectedNews(PAGE_SIZE, offset, search),
  });
  const detail = useQuery({
    queryKey: ["rejected-news", "detail", selectedId],
    queryFn: () => getRejectedNewsById(selectedId as number),
    enabled: selectedId != null,
  });
  const restore = useMutation({
    mutationFn: restoreRejectedNews,
    onSuccess: async () => {
      setRestoreItem(null);
      setSelectedId(null);
      await queryClient.invalidateQueries({ queryKey: ["rejected-news"] });
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
    },
  });

  const columns: Array<DataTableColumn<RejectedNewsItem>> = [
    {
      key: "id",
      header: "ID",
      className: "w-24 tabular-nums text-text-muted",
      render: (row) => offset + (list.data?.items ?? []).indexOf(row) + 1,
    },
    { key: "summary", header: "News summary", headerClassName: "min-w-[24rem]", render: (row) => <p className="max-w-2xl whitespace-normal text-small leading-6" dir="auto">{row.summary}</p> },
    { key: "event", header: "Date and time", render: (row) => <span className="whitespace-nowrap">{formatDateTime(row.message_datetime ?? row.received_at)}</span> },
    { key: "reason", header: "Rejection", render: (row) => <div className="space-y-2"><StatusBadge label={reasonLabel(row.rejection_type)} variant={row.rejection_type === "duplicate" ? "neutral" : "warning"} /><p className="max-w-xs text-caption text-text-muted">{row.rejection_reason_en}</p><p className="max-w-xs text-caption text-text-muted text-right" dir="rtl">{row.rejection_reason_ar}</p></div> },
    { key: "source", header: "Source", render: (row) => row.source_name ?? row.source_platform ?? "Unknown" },
  ];

  const selected = detail.data;
  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));
  return <div className="space-y-6">
    <section><p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">Pipeline review</p><h1 className="text-h3 font-semibold text-text-primary">Rejected news</h1></section>
    <section className="rounded-xl border border-border bg-surface-raised p-4"><Input value={search} placeholder="Search report or source" onChange={(event) => { setSearch(event.target.value); setPage(1); }} /></section>
    <DataTable
      columns={columns}
      rows={list.data?.items ?? []}
      getRowKey={(row) => String(row.id)}
      loading={list.isLoading}
      error={list.isError}
      emptyState={<EmptyState title="No rejected news" description="Matching reports from the latest 7 days will appear here automatically." />}
      errorState={<EmptyState title="Could not load rejected news" description="Try again." />}
      actions={(row) => <div className="flex gap-2"><Button variant="secondary" onClick={() => setSelectedId(row.id)}>View details</Button><Button onClick={() => setRestoreItem(row)}>Move to incidents</Button></div>}
    />
    <div className="flex items-center justify-between"><p className="text-small text-text-muted">{list.data?.total ?? 0} rejected reports</p><div className="flex gap-2"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</Button></div></div>
    {selectedId != null ? <Dialog title="Rejected news details" eyebrow={`Raw message #${selectedId}`} size="lg" onClose={() => setSelectedId(null)}>{detail.isLoading ? <p>Loading...</p> : selected ? <div className="space-y-5"><div><p className="text-caption font-semibold uppercase text-text-muted">News summary</p><p className="mt-2 leading-7" dir="auto">{selected.summary}</p></div><div><p className="text-caption font-semibold uppercase text-text-muted">Original source text</p><p className="mt-2 whitespace-pre-wrap leading-7" dir="auto">{selected.khabar}</p></div><div className="grid gap-4 sm:grid-cols-2"><div><p className="text-caption font-semibold text-text-muted">Event date and time</p><p>{formatDateTime(selected.message_datetime ?? selected.received_at)}</p></div><div><p className="text-caption font-semibold text-text-muted">Source</p><p>{selected.source_name ?? selected.source_platform ?? "Unknown"}</p></div></div><div className="rounded-xl border border-warning/30 bg-warning/5 p-4"><StatusBadge label={reasonLabel(selected.rejection_type)} variant="warning" /><p className="mt-3 text-small">{selected.rejection_reason_en}</p><p className="mt-2 text-small text-right" dir="rtl">{selected.rejection_reason_ar}</p></div><div className="flex justify-end"><Button onClick={() => setRestoreItem(selected)}>Move to incidents</Button></div></div> : <p>Rejected news was not found.</p>}</Dialog> : null}
    {restoreItem ? <ConfirmDialog title="Move report to incidents?" description="This overrides the rejection and sends the report back through extraction, village matching, condition matching, and duplicate checking. It will appear in Incidents after processing succeeds." confirmLabel="Move to incidents" isLoading={restore.isPending} onCancel={() => setRestoreItem(null)} onConfirm={() => restore.mutateAsync(restoreItem.id)} /> : null}
  </div>;
};
