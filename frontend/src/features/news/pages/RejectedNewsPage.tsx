import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ConfirmDialog, DataTable, Dialog, EmptyState, Input, type DataTableColumn } from "../../../components/ui";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDateTime } from "../../../lib/formatters";
import { getRejectedNews, getRejectedNewsById, restoreRejectedNews } from "../api";
import type { RejectedNewsItem } from "../types";

const PAGE_SIZE = 25;

const reasonLabel = (type: RejectedNewsItem["rejection_type"]) => ({
  not_relevant: "Not relevant",
  uncertain: "Uncertain",
  duplicate: "Duplicate",
  rejected: "Rejected",
}[type]);

const reasonVariant = (type: RejectedNewsItem["rejection_type"]) =>
  type === "duplicate" ? "neutral" as const : type === "uncertain" ? "warning" as const : "danger" as const;

const twoLineClampClass =
  "overflow-hidden text-ellipsis [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]";

export const RejectedNewsPage = () => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reasonItem, setReasonItem] = useState<RejectedNewsItem | null>(null);
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
      header: "#",
      headerClassName: "w-14 whitespace-nowrap",
      cellClassName: "w-14 tabular-nums text-text-muted",
      mobileLabel: "Record",
      render: (row) => offset + (list.data?.items ?? []).indexOf(row) + 1,
    },
    {
      key: "summary",
      header: "News report",
      headerClassName: "w-[48%] min-w-[22rem]",
      cellClassName: "w-[48%] min-w-[22rem]",
      render: (row) => (
        <div className="space-y-1.5">
          <p
            className={`${twoLineClampClass} whitespace-normal text-small font-medium leading-6 text-text-primary`}
            dir="auto"
          >
            {row.summary || row.khabar}
          </p>
          <p className="text-caption text-text-muted">
            Raw message #{row.id}
          </p>
        </div>
      ),
    },
    {
      key: "event",
      header: "Received",
      headerClassName: "w-[12rem] whitespace-nowrap",
      cellClassName: "w-[12rem]",
      mobileLabel: "Date and time",
      render: (row) => (
        <span className="whitespace-nowrap">
          {formatDateTime(row.message_datetime ?? row.received_at)}
        </span>
      ),
    },
    {
      key: "source",
      header: "Source",
      headerClassName: "w-[10rem]",
      cellClassName: "w-[10rem]",
      render: (row) => (
        <span className="break-words">
          {row.source_name ?? row.source_platform ?? "Unknown"}
        </span>
      ),
    },
    {
      key: "reason",
      header: "Status",
      headerClassName: "w-[9rem] whitespace-nowrap",
      cellClassName: "w-[9rem]",
      render: (row) => (
        <StatusBadge
          label={reasonLabel(row.rejection_type)}
          variant={reasonVariant(row.rejection_type)}
        />
      ),
    },
  ];

  const selected = detail.data;
  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));
  return <div className="space-y-6">
    <section className="space-y-4">
      <div className="space-y-1">
        <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
          Pipeline review
        </p>
        <h1 className="text-h3 font-semibold text-text-primary">Rejected news</h1>
        <p className="max-w-2xl text-small leading-6 text-text-muted">
          Review reports stopped by the news pipeline and restore any report that should become an incident.
        </p>
      </div>
      <div className="rounded-xl border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)] sm:p-5">
        <p className="text-caption font-semibold uppercase text-text-muted">
          Rejected in the last 7 days
        </p>
        <p className="mt-2 text-h3 font-semibold text-text-primary">
          {list.data?.total ?? 0}
        </p>
      </div>
    </section>

    <section className="rounded-xl border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)] sm:p-5">
      <label className="mb-2 block text-small font-semibold text-text-primary" htmlFor="rejected-news-search">
        Search rejected news
      </label>
      <Input
        id="rejected-news-search"
        value={search}
        placeholder="Search the report or source"
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
      />
    </section>

    <section className="space-y-3">
      <div>
        <h2 className="text-h4 font-semibold text-text-primary">Rejected reports</h2>
        <p className="text-small text-text-muted">
          Select “Why rejected?” to read the pipeline decision.
        </p>
      </div>
    <DataTable
      columns={columns}
      rows={list.data?.items ?? []}
      getRowKey={(row) => String(row.id)}
      minWidth="920px"
      clientSort={false}
      loading={list.isLoading}
      error={list.isError}
      emptyState={<EmptyState title="No rejected news" description="Matching reports from the latest 7 days will appear here automatically." />}
      errorState={<EmptyState title="Could not load rejected news" description="Try again." />}
      actions={(row) => (
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            className="whitespace-nowrap"
            onClick={() => setReasonItem(row)}
          >
            Why rejected?
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="whitespace-nowrap"
            onClick={() => setSelectedId(row.id)}
          >
            View report
          </Button>
          <Button
            type="button"
            className="whitespace-nowrap"
            onClick={() => setRestoreItem(row)}
          >
            Move to incidents
          </Button>
        </div>
      )}
    />
    </section>

    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-small text-text-muted">
        Showing {list.data?.items.length ?? 0} of {list.data?.total ?? 0} rejected reports · Page {page} of {totalPages}
      </p>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
        <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </div>

    {reasonItem ? (
      <Dialog
        title="Why this news was rejected"
        eyebrow={`Raw message #${reasonItem.id}`}
        onClose={() => setReasonItem(null)}
      >
        <div className="space-y-5">
          <div className="rounded-xl border border-danger/30 bg-danger/5 p-4 sm:p-5">
            <StatusBadge
              label={reasonLabel(reasonItem.rejection_type)}
              variant={reasonVariant(reasonItem.rejection_type)}
            />
            <div className="mt-4 space-y-4">
              <div>
                <p className="text-caption font-semibold uppercase text-text-muted">Reason</p>
                <p className="mt-1 text-body leading-7 text-text-primary">
                  {reasonItem.rejection_reason_en || reasonItem.rejection_reason}
                </p>
              </div>
              {reasonItem.rejection_reason_ar ? (
                <div className="border-t border-danger/20 pt-4">
                  <p className="text-caption font-semibold uppercase text-text-muted">السبب</p>
                  <p className="mt-1 text-right text-body leading-8 text-text-primary" dir="rtl" lang="ar">
                    {reasonItem.rejection_reason_ar}
                  </p>
                </div>
              ) : null}
            </div>
          </div>
          <div>
            <p className="text-caption font-semibold uppercase text-text-muted">News summary</p>
            <p className="mt-2 leading-7 text-text-primary" dir="auto">{reasonItem.summary}</p>
          </div>
          <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={() => setReasonItem(null)}>Close</Button>
            <Button type="button" onClick={() => {
              setReasonItem(null);
              setRestoreItem(reasonItem);
            }}>
              Move to incidents
            </Button>
          </div>
        </div>
      </Dialog>
    ) : null}

    {selectedId != null ? (
      <Dialog title="Rejected news details" eyebrow={`Raw message #${selectedId}`} size="lg" onClose={() => setSelectedId(null)}>
        {detail.isLoading ? (
          <p>Loading report...</p>
        ) : selected ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge label={reasonLabel(selected.rejection_type)} variant={reasonVariant(selected.rejection_type)} />
              <Button type="button" variant="secondary" onClick={() => {
                setSelectedId(null);
                setReasonItem(selected);
              }}>
                Why rejected?
              </Button>
            </div>
            <div>
              <p className="text-caption font-semibold uppercase text-text-muted">News summary</p>
              <p className="mt-2 leading-7" dir="auto">{selected.summary}</p>
            </div>
            <div className="rounded-xl border border-border bg-surface p-4">
              <p className="text-caption font-semibold uppercase text-text-muted">Original source text</p>
              <p className="mt-2 whitespace-pre-wrap leading-7" dir="auto">{selected.khabar}</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-caption font-semibold text-text-muted">Event date and time</p>
                <p className="mt-1">{formatDateTime(selected.message_datetime ?? selected.received_at)}</p>
              </div>
              <div>
                <p className="text-caption font-semibold text-text-muted">Source</p>
                <p className="mt-1">{selected.source_name ?? selected.source_platform ?? "Unknown"}</p>
              </div>
            </div>
            <div className="flex justify-end border-t border-border pt-4">
              <Button onClick={() => setRestoreItem(selected)}>Move to incidents</Button>
            </div>
          </div>
        ) : (
          <p>Rejected news was not found.</p>
        )}
      </Dialog>
    ) : null}
    {restoreItem ? <ConfirmDialog title="Move report to incidents?" description="This overrides the rejection and sends the report back through extraction, village matching, condition matching, and duplicate checking. It will appear in Incidents after processing succeeds." confirmLabel="Move to incidents" isLoading={restore.isPending} onCancel={() => setRestoreItem(null)} onConfirm={() => restore.mutateAsync(restoreItem.id)} /> : null}
  </div>;
};
