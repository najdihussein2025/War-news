import { useContext, useEffect, useState, type FormEvent } from "react";
import { ShellContext } from "../../../app/AppShell";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, Dialog, EmptyState, FormField, Input, Label, type DataTableColumn } from "../../../components/ui";
import { formatDateTime } from "../../../lib/formatters";
import { useExportLogs } from "../../../mocks/useExportLogs";
import type { ExportStatus, MockExportLog } from "../../../mocks/mockExportLogs";

const statusVariant = (status: ExportStatus) =>
  status === "completed" ? "success" : status === "failed" ? "danger" : "warning";

export const ExportPage = () => {
  const { data, isLoading, isError } = useExportLogs();
  const shell = useContext(ShellContext);
  const [logs, setLogs] = useState(data);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [form, setForm] = useState({ from: "", to: "", status: "all", allFields: true });

  useEffect(() => {
    shell?.setPageAction(<Button type="button" className="w-full sm:w-auto" onClick={() => setIsDialogOpen(true)}>New Export</Button>);
    return () => shell?.setPageAction(null);
  }, [shell]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const id = `exp_${Date.now()}`;
    const nextLog: MockExportLog = {
      id,
      requested_by: "Super Admin",
      timestamp: "2026-08-10T12:00:00+03:00",
      status: "running",
      row_count: null,
      file_name: "war-news-custom-export.csv",
    };
    setLogs((current) => [nextLog, ...current]);
    setIsDialogOpen(false);
    shell?.showToast("Export started.");
    window.setTimeout(() => {
      setLogs((current) => current.map((log) => log.id === id ? { ...log, status: "completed", row_count: 318 } : log));
      shell?.showToast("Export completed.");
    }, 1800);
  };

  const columns: Array<DataTableColumn<MockExportLog>> = [
    { key: "time", header: "Timestamp", render: (row) => formatDateTime(row.timestamp), sortValue: (row) => new Date(row.timestamp).getTime() },
    { key: "requested", header: "Requested by", render: (row) => <span className="font-semibold text-text-primary">{row.requested_by}</span>, sortValue: (row) => row.requested_by },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="space-y-2">
          <StatusBadge label={row.status} variant={statusVariant(row.status)} />
          {row.status === "running" ? <div className="h-1.5 w-28 overflow-hidden rounded-full bg-surface-muted"><div className="h-full w-1/2 rounded-full bg-accent" /></div> : null}
        </div>
      ),
      sortValue: (row) => row.status,
    },
    { key: "rows", header: "Row count", render: (row) => row.row_count?.toLocaleString() ?? "Pending", sortValue: (row) => row.row_count ?? 0 },
    { key: "file", header: "File", render: (row) => <span className="text-text-muted">{row.file_name}</span>, sortValue: (row) => row.file_name },
  ];

  return (
    <>
      <DataTable
        columns={columns}
        rows={logs}
        getRowKey={(row) => row.id}
        loading={isLoading}
        error={isError}
        minWidth="980px"
        emptyState={<EmptyState title="No exports yet" description="Export history will appear here." />}
        errorState={<EmptyState title="Could not load exports" description="The mocked error state is ready for a future API failure." />}
        actions={(row) => <Button type="button" variant="secondary" className="h-9" disabled={row.status !== "completed"}>Download</Button>}
      />

      {isDialogOpen ? (
        <Dialog title="New Export" onClose={() => setIsDialogOpen(false)}>
          <form className="space-y-4" onSubmit={submit}>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="export-from" label="From">
                <Input id="export-from" type="date" value={form.from} onChange={(event) => setForm({ ...form, from: event.target.value })} />
              </FormField>
              <FormField id="export-to" label="To">
                <Input id="export-to" type="date" value={form.to} onChange={(event) => setForm({ ...form, to: event.target.value })} />
              </FormField>
            </div>
            <div className="space-y-2">
              <Label htmlFor="export-status">Status scope</Label>
              <select id="export-status" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                <option value="all">All statuses</option>
                <option value="approved">Approved only</option>
                <option value="flagged">Flagged for verification</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>
            <label className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3 text-small font-semibold text-text-primary">
              <input type="checkbox" checked={form.allFields} onChange={(event) => setForm({ ...form, allFields: event.target.checked })} />
              Include all incident fields
            </label>
            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="secondary" onClick={() => setIsDialogOpen(false)}>Cancel</Button>
              <Button type="submit">Start export</Button>
            </div>
          </form>
        </Dialog>
      ) : null}
    </>
  );
};
