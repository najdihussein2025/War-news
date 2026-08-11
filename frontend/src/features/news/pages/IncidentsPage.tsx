import { useContext, useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, DataTable, Dialog, EmptyState, Input, Label, type DataTableColumn } from "../../../components/ui";
import { formatDate, formatRelativeTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { useIncidents } from "../../../mocks/useIncidents";
import type { IncidentSourceType, MockIncident } from "../../../mocks/mockIncidents";

const sources: IncidentSourceType[] = ["Telegram", "API", "Manual"];
const PAGE_SIZE = 15;

const sourceVariant = (source: IncidentSourceType) =>
  source === "Telegram" ? "accent" : source === "API" ? "neutral" : "warning";

export const IncidentsPage = () => {
  const { data, isLoading, isError } = useIncidents();
  const shell = useContext(ShellContext);
  const navigate = useNavigate();
  const location = useLocation();
  const roleBase = roleBaseFromPath(location.pathname);
  const [params, setParams] = useSearchParams();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [compareIncident, setCompareIncident] = useState<MockIncident | null>(null);

  const village = params.get("village") ?? "";
  const source = (params.get("source") as IncidentSourceType | null) ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const flaggedOnly = params.get("flagged") === "1";
  const hasFilters = Boolean(village || source || from || to || flaggedOnly);

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    setVisibleCount(PAGE_SIZE);
    setParams(next);
  };

  const filtered = useMemo(() => {
    return data.filter((incident) => {
      const date = incident.event_date.slice(0, 10);
      const qualityFlagged = !incident.matched || incident.duplicate_flag === "possible";
      return (
        (!village || incident.village.toLowerCase().includes(village.toLowerCase())) &&
        (!source || incident.source === source) &&
        (!from || date >= from) &&
        (!to || date <= to) &&
        (!flaggedOnly || qualityFlagged)
      );
    });
  }, [data, flaggedOnly, from, source, to, village]);

  const flaggedCount = data.filter((incident) => !incident.matched).length;
  const duplicateCount = data.filter((incident) => incident.duplicate_flag === "possible").length;

  const columns: Array<DataTableColumn<MockIncident>> = [
    {
      key: "village",
      header: "Village",
      render: (row) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-text-primary">{row.village}</span>
            {!row.matched ? <StatusBadge label="Needs verification" variant="warning" /> : null}
            {row.duplicate_flag === "possible" ? (
              <button type="button" onClick={() => setCompareIncident(row)}>
                <StatusBadge label="Possible duplicate" variant="warning" />
              </button>
            ) : null}
          </div>
          <p className="text-caption text-text-muted">{row.khabar}</p>
        </div>
      ),
      sortValue: (row) => row.village,
    },
    { key: "condition", header: "Condition", render: (row) => row.condition, sortValue: (row) => row.condition },
    { key: "date", header: "Date", render: (row) => formatDate(row.event_date), sortValue: (row) => new Date(row.event_date).getTime() },
    {
      key: "source",
      header: "Source",
      render: (row) => (
        <div className="space-y-1">
          <StatusBadge label={row.source} variant={sourceVariant(row.source)} />
          <p className="text-caption text-text-muted">{row.source_reference}</p>
        </div>
      ),
      sortValue: (row) => row.source,
    },
    { key: "created", header: "Published", render: (row) => formatRelativeTime(row.created_at), sortValue: (row) => new Date(row.created_at).getTime() },
  ];

  const visibleRows = filtered.slice(0, visibleCount);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">Flagged for verification</p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">{flaggedCount}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <p className="text-caption font-semibold uppercase text-text-muted">Possible duplicates</p>
          <p className="mt-2 text-h3 font-semibold text-text-primary">{duplicateCount}</p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface-raised p-4">
        <div className="grid gap-4 lg:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="village-filter">Village</Label>
            <Input id="village-filter" value={village} onChange={(event) => updateParam("village", event.target.value)} placeholder="Search village" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="source-filter">Source</Label>
            <select id="source-filter" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary" value={source} onChange={(event) => updateParam("source", event.target.value)}>
              <option value="">All sources</option>
              {sources.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="from-filter">From</Label>
            <Input id="from-filter" type="date" value={from} onChange={(event) => updateParam("from", event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="to-filter">To</Label>
            <Input id="to-filter" type="date" value={to} onChange={(event) => updateParam("to", event.target.value)} />
          </div>
          <label className="flex h-11 items-center gap-3 rounded-md border border-border bg-surface px-3 text-small font-semibold text-text-primary">
            <input type="checkbox" checked={flaggedOnly} onChange={(event) => updateParam("flagged", event.target.checked ? "1" : "")} />
            Show flagged only
          </label>
        </div>
        {hasFilters ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-small font-semibold text-text-muted">Active filters</span>
            {flaggedOnly ? <StatusBadge label="Flagged only" variant="warning" /> : null}
            {village ? <StatusBadge label={`Village: ${village}`} /> : null}
            {source ? <StatusBadge label={`Source: ${source}`} /> : null}
            {from ? <StatusBadge label={`From: ${from}`} /> : null}
            {to ? <StatusBadge label={`To: ${to}`} /> : null}
            <Button type="button" variant="ghost" className="h-9" onClick={() => setParams({})}>Clear filters</Button>
          </div>
        ) : null}
      </div>

      <DataTable
        columns={columns}
        rows={visibleRows}
        getRowKey={(row) => row.id}
        loading={isLoading}
        error={isError}
        minWidth="1100px"
        emptyState={<EmptyState title={hasFilters ? "No matching incidents" : "No incidents yet"} description={hasFilters ? "Adjust or clear the filters to broaden the results." : "Auto-published incidents will appear here after parsing and dedup checks run."} />}
        errorState={<EmptyState title="Could not load incidents" description="The mocked error state is ready for a future API failure." />}
        actions={(row) => (
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" className="h-9" onClick={() => navigate(`${roleBase}/incidents/${row.id}`)}>View</Button>
            <Button type="button" variant="ghost" className="h-9" onClick={() => navigate(`${roleBase}/incidents/${row.id}?edit=1`)}>Edit</Button>
          </div>
        )}
      />

      {visibleCount < filtered.length ? (
        <div className="flex justify-center">
          <Button type="button" variant="secondary" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
            Load more
          </Button>
        </div>
      ) : null}

      {compareIncident ? (
        <Dialog title="Compare possible duplicate" size="lg" onClose={() => setCompareIncident(null)}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-border bg-surface p-4">
              <StatusBadge label="Published incident" variant="accent" />
              <h2 className="mt-3 text-h4 font-semibold text-text-primary">{compareIncident.village}</h2>
              <p className="mt-2 text-small text-text-muted">{compareIncident.khabar}</p>
              <p className="mt-4 text-caption text-text-muted">{compareIncident.source} / {compareIncident.source_reference}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <StatusBadge label="Suspected match" variant="warning" />
              <h2 className="mt-3 text-h4 font-semibold text-text-primary">{compareIncident.village}</h2>
              <p className="mt-2 text-small text-text-muted">Earlier report with similar village, condition, and event window. Published for visibility after soft dedup flag.</p>
              <p className="mt-4 text-caption text-text-muted">mock:dedup-neighbor</p>
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Button type="button" onClick={() => shell?.showToast("Compare resolution is mocked for now.")}>Mark reviewed</Button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
};
