import { useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
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
import { getBeirutDate, normalizeDateInputValue } from "../../../lib/localDate";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { ConditionSelect } from "../components/ConditionSelect";
import { useConditionsQuery, useIncidentStream, useIncidentsQuery, useVillagesQuery } from "../hooks";
import { createIncident, getFilteredNews, reviewIncident } from "../api";
import { useContentSourcesQuery } from "../../sources/hooks";
import type { FilteredNewsItem, Incident } from "../types";

const DEFAULT_PAGE_SIZE = 150;
const PAGE_SIZE_OPTIONS = new Set([50, 100, 150]);
const DEFAULT_EVENT_DATE_FROM = "2026-08-20";
const NEWS_PAGE_SIZE = 100;
const DEFAULT_NEWS_DATE_FROM = "2026-08-01";
const twoLineClampClass =
  "overflow-hidden text-ellipsis [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]";
const threeLineClampClass =
  "overflow-hidden text-ellipsis [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]";

const parsePageSize = (value: string | null) => {
  const parsed = Number(value);
  return PAGE_SIZE_OPTIONS.has(parsed) ? parsed : DEFAULT_PAGE_SIZE;
};

const newsStatusVariant = (status: string) => {
  if (status === "materialized") return "success" as const;
  if (status === "duplicate") return "neutral" as const;
  if (status === "error") return "danger" as const;
  return "accent" as const;
};

const eventDay = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Beirut",
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));

const eventHour = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Beirut",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));

const relatedSourceNotes = (row: Incident, pageRows: Incident[]): string[] => {
  const notes: string[] = [];
  const sameBulletin = pageRows.filter(
    (other) =>
      other.id !== row.id &&
      row.raw_message_id != null &&
      other.raw_message_id === row.raw_message_id,
  );
  const sameGroup = pageRows.filter(
    (other) =>
      other.id !== row.id &&
      row.story_group_id != null &&
      other.story_group_id === row.story_group_id,
  );
  const sameLocation = [...sameBulletin, ...sameGroup].find((other) => {
    if (row.village_id == null || other.village_id == null) {
      return other.story_group_id != null && other.story_group_id === row.story_group_id;
    }
    return other.village_id === row.village_id;
  });
  const otherVillage = sameBulletin.find(
    (other) =>
      row.village_id != null &&
      other.village_id != null &&
      other.village_id !== row.village_id,
  );
  if (sameLocation) {
    notes.push(
      `Related: ${sameLocation.condition || "related action"}, same location`,
    );
  }
  if (otherVillage) {
    notes.push("Related: same bulletin, different village");
  } else if (!sameLocation && sameBulletin.length > 0) {
    notes.push("Source: same bulletin as another village on this page");
  }
  return notes;
};

const preMaterializationStatus = (
  rawStatus: string | null,
  incidentId: string | null,
) => {
  if (incidentId) {
    return null;
  }
  if (rawStatus === "parsed") {
    return { label: "Processing", variant: "accent" as const };
  }
  return { label: "Processing", variant: "neutral" as const };
};

const PreMaterializationStatusBadge = ({ row }: { row: Incident }) => {
  const status = preMaterializationStatus(row.raw_status, row.id);
  return status ? (
    <StatusBadge label={status.label} variant={status.variant} />
  ) : null;
};

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
  const location = useLocation();
  const roleBase = roleBaseFromPath(location.pathname);
  const [params, setParams] = useSearchParams();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [cursorHistory, setCursorHistory] = useState<string[]>([]);
  const [reviewRow, setReviewRow] = useState<Incident | null>(null);
  const [reviewError, setReviewError] = useState("");
  const [isReviewing, setIsReviewing] = useState(false);
  // Filtered news state
  const [newsPage, setNewsPage] = useState(1);
  const [newsDateFrom, setNewsDateFrom] = useState(DEFAULT_NEWS_DATE_FROM);
  const [newsDateTo, setNewsDateTo] = useState(getBeirutDate());
  const [newsSourceName, setNewsSourceName] = useState("");
  const [newsStatus, setNewsStatus] = useState("");
  const [newsSearch, setNewsSearch] = useState("");
  const newsOffset = (newsPage - 1) * NEWS_PAGE_SIZE;

  const cursor = cursorHistory.at(-1);
  const page = cursorHistory.length + 1;
  const village = params.get("village") ?? "";
  const condition = params.get("condition") ?? "";
  const sourceName = params.get("source_name") ?? "";
  const verificationStatus = params.get("verification_status") as Incident["verification_status"] | "";
  const eventDateFrom = normalizeDateInputValue(params.get("event_date_from")) || DEFAULT_EVENT_DATE_FROM;
  const eventDateTo = normalizeDateInputValue(params.get("event_date_to")) || getBeirutDate();
  const sortOrder = (params.get("sort_order") as "newest" | "oldest" | null) ?? "newest";
  const duplicateOnly = params.get("duplicate_only") === "true";
  const hasCasualties = params.get("has_casualties") === "true";
  const pageSize = parsePageSize(params.get("page_size"));
  const hasFilters = Boolean(
    village || condition || sourceName || verificationStatus || eventDateFrom || eventDateTo || duplicateOnly || hasCasualties,
  );

  const filters = useMemo(
    () => ({
      limit: pageSize,
      cursor,
      village,
      condition,
      sourceName,
      verificationStatus: verificationStatus || undefined,
      eventDateFrom,
      eventDateTo,
      duplicateOnly,
      hasCasualties,
      sortOrder,
    }),
    [
      condition,
      eventDateFrom,
      eventDateTo,
      duplicateOnly,
      hasCasualties,
      pageSize,
      cursor,
      sortOrder,
      sourceName,
      verificationStatus,
      village,
    ],
  );

  const { data, isLoading, isError, isFetching, refetch } =
    useIncidentsQuery(filters);
  const { isReconnecting } = useIncidentStream(filters);
  const {
    data: conditions = [],
    isLoading: isConditionsLoading,
    isError: isConditionsError,
  } = useConditionsQuery();
  const {
    data: villages = [],
    isLoading: isVillagesLoading,
  } = useVillagesQuery();
  const {
    data: contentSources = [],
    isLoading: isContentSourcesLoading,
  } = useContentSourcesQuery();
  useLiveQueryTitleAddon(data?.latest_incident_at ?? null, isFetching);

  // Filtered news query — always related to incidents only
  const newsFilters = useMemo(
    () => ({
      limit: NEWS_PAGE_SIZE,
      offset: newsOffset,
      eventDateFrom: newsDateFrom || undefined,
      eventDateTo: newsDateTo || undefined,
      sourceName: newsSourceName || undefined,
      status: newsStatus || undefined,
      relatedOnly: true,
      search: newsSearch || undefined,
    }),
    [newsDateFrom, newsDateTo, newsOffset, newsSearch, newsSourceName, newsStatus],
  );
  const newsQuery = useQuery({
    queryKey: ["filtered-news", newsFilters],
    queryFn: () => getFilteredNews(newsFilters),
  });
  const newsRows = newsQuery.data?.items ?? [];
  const newsTotal = newsQuery.data?.total ?? 0;
  const newsTotalPages = Math.max(1, Math.ceil(newsTotal / NEWS_PAGE_SIZE));
  const newsSourceOptions = useMemo(() => {
    const names = new Set(newsRows.map((r) => r.source_name).filter(Boolean) as string[]);
    return [...names].sort().map((name) => ({ value: name, label: name }));
  }, [newsRows]);

  const newsColumns: Array<DataTableColumn<FilteredNewsItem>> = [
    {
      key: "index",
      header: "#",
      headerClassName: "w-12 whitespace-nowrap",
      cellClassName: "w-12 tabular-nums text-text-muted",
      render: (row) => newsOffset + newsRows.indexOf(row) + 1,
    },
    {
      key: "time",
      header: "Event Day / Hour",
      headerClassName: "w-[12rem] whitespace-nowrap",
      cellClassName: "w-[12rem]",
      render: (row) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-text-primary">{eventDay(row.event_at)}</p>
          <p className="text-caption font-mono text-accent">{eventHour(row.event_at)}</p>
        </div>
      ),
    },
    {
      key: "report",
      header: "Filtered News (Khabar)",
      headerClassName: "min-w-[24rem]",
      cellClassName: "min-w-[24rem]",
      render: (row) => (
        <div className="space-y-1.5">
          <p className={`${threeLineClampClass} whitespace-normal leading-6 text-text-primary`} dir="auto">
            {row.khabar}
          </p>
          <div className="flex flex-wrap items-center gap-2 text-caption text-text-muted">
            <span>Raw #{row.id}</span>
            {row.external_message_id ? <span>· ID: {row.external_message_id}</span> : null}
            {row.source_name ? (
              <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-medium text-text-secondary">
                {row.source_name}
              </span>
            ) : null}
          </div>
        </div>
      ),
    },
    {
      key: "incident_link",
      header: "Related Incident",
      headerClassName: "w-[16rem]",
      cellClassName: "w-[16rem]",
      render: (row) => {
        if (!row.incident_id) {
          return (
            <span className="inline-flex items-center rounded-md bg-surface-subtle px-2.5 py-1 text-caption text-text-muted">
              No incident linked
            </span>
          );
        }
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
              <span className="font-medium text-text-primary text-small">Incident linked</span>
            </div>
            {row.village_name || row.condition_name ? (
              <p className="text-caption text-text-secondary">
                {row.village_name ? <span>📍 {row.village_name} </span> : null}
                {row.condition_name ? <span>⚡ {row.condition_name}</span> : null}
              </p>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "status",
      header: "Pipeline Status",
      headerClassName: "w-[10rem]",
      cellClassName: "w-[10rem]",
      render: (row) => (
        <StatusBadge label={row.status} variant={newsStatusVariant(row.status)} />
      ),
    },
    {
      key: "reason",
      header: "Relevance Reason",
      headerClassName: "w-[16rem]",
      cellClassName: "w-[16rem]",
      render: (row) => (
        <p className={`${threeLineClampClass} text-small leading-5 text-text-muted`}>
          {row.reasoning ?? (row.verdict === "relevant" ? "Classified as relevant" : "Relevant incident news")}
        </p>
      ),
    },
  ];
  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const flaggedCount = data?.needs_verification_count ?? 0;
  const casualtiesCount = data?.casualties_count ?? 0;
  const verificationOptions: SelectOption[] = [
    { value: "needs_verification", label: "Needs verification" },
    { value: "verified", label: "Verified" },
  ];
  const verificationBadge = (row: Incident) => {
    if (row.verification_status === "verified") return { label: "Verified", variant: "success" as const };
    if (row.verification_status === "rejected") return { label: "Rejected", variant: "danger" as const };
    if (row.verification_status === "needs_verification" && row.duplicate_flag === "possible") {
      return { label: "Needs verification", variant: "warning" as const };
    }
    return null;
  };
  const sourceOptions = useMemo<SelectOption[]>(() => {
    const channels = new Map<string, SelectOption>();
    for (const source of contentSources) {
      if (source.source_name && !channels.has(source.source_name)) {
        channels.set(source.source_name, {
          value: source.source_name,
          label: source.source_name,
        });
      }
    }
    return [...channels.values()].sort((left, right) =>
      left.label.localeCompare(right.label),
    );
  }, [contentSources]);
  const dateSortOptions: SelectOption[] = [
    { value: "newest", label: "Newest to oldest" },
    { value: "oldest", label: "Oldest to newest" },
  ];
  const pageSizeOptions: SelectOption[] = [
    { value: "50", label: "50 per page" },
    { value: "100", label: "100 per page" },
    { value: "150", label: "150 per page" },
  ];

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    setCursorHistory([]);
    setParams(next);
  };

  const columns: Array<DataTableColumn<Incident>> = [
    {
      key: "number",
      header: "#",
      headerClassName: "w-14 whitespace-nowrap",
      cellClassName: "w-14 tabular-nums text-text-muted",
      mobileLabel: "Record",
      render: (row) => (page - 1) * pageSize + rows.indexOf(row) + 1,
    },
    {
      key: "village",
      header: "Village",
      headerClassName: "w-[34%] min-w-[18rem]",
      cellClassName: "w-[34%] min-w-[18rem]",
      render: (row) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-text-primary">
              {row.village || "Unknown village"}
            </span>
            <PreMaterializationStatusBadge row={row} />
            {row.duplicate_flag === "possible" ? (
              <StatusBadge label="Possible duplicate" variant="warning" />
            ) : null}
            {row.duplicate_level === "low" ? (
              <StatusBadge
                label={`Low similarity${row.duplicate_similarity_score == null ? "" : ` — ${Math.round(row.duplicate_similarity_score * 100)}%`}`}
                variant="neutral"
              />
            ) : null}
            {row.duplicate_level === "high" ? (
              <StatusBadge
                label={`Automatically merged${row.duplicate_similarity_score == null ? "" : ` — ${Math.round(row.duplicate_similarity_score * 100)}%`}`}
                variant="success"
              />
            ) : null}
            {row.details_pending ? (
              <StatusBadge label="Details pending" variant="neutral" />
            ) : null}
          </div>
          <p
            className={`${twoLineClampClass} break-words text-caption leading-6 text-text-muted`}
            dir="auto"
          >
            {row.khabar}
          </p>
          {relatedSourceNotes(row, rows).map((note) => (
            <p key={note} className="text-caption text-text-muted">
              {note}
            </p>
          ))}
        </div>
      ),
    },
    {
      key: "condition",
      header: "Condition",
      headerClassName: "w-[12rem]",
      cellClassName: "w-[12rem]",
      render: (row) => (
        <div className="space-y-1">
          <p className={`${twoLineClampClass} text-small leading-6 text-text-primary`}>
            {row.condition || "No data"}
          </p>
          {row.condition_ar ? (
            <p className={`${twoLineClampClass} text-caption leading-6 text-text-muted`} dir="rtl" lang="ar">
              {row.condition_ar}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      key: "verification",
      header: "Verification",
      headerClassName: "w-[9.5rem] whitespace-nowrap",
      cellClassName: "w-[9.5rem]",
      render: (row) => (
        <div className="space-y-1">
          {verificationBadge(row) ? <StatusBadge {...verificationBadge(row)!} /> : null}
          {row.verification_reason ? <p className="text-caption text-text-muted">{row.verification_reason}</p> : null}
        </div>
      ),
    },
    {
      key: "date",
      header: "Event",
      headerClassName: "w-[10rem] whitespace-nowrap",
      cellClassName: "w-[10rem]",
      mobileLabel: "Event date / time",
      render: (row) => (
        <div className="space-y-1 whitespace-nowrap">
          <p>{formatDate(row.event_date)}</p>
          <p className="text-caption text-text-muted">
            {row.event_time ? row.event_time.slice(0, 5) : "Time not recorded"}
          </p>
        </div>
      ),
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
          {isReconnecting ? (
            <p className="text-small text-warning">
              Live feed reconnecting...
            </p>
          ) : isFetching ? (
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
              Reported casualties
            </p>
            <p className="mt-2 text-h3 font-semibold text-text-primary">
              {casualtiesCount}
            </p>
          </div>
        </div>
      </section>

      <>
          <section className="overflow-visible rounded-[1.125rem] border border-border bg-surface-raised shadow-raised">
            <div className="flex flex-col gap-4 rounded-t-[1.125rem] border-b border-border bg-[linear-gradient(180deg,rgba(234,242,251,0.82)_0%,rgba(255,255,255,0.98)_100%)] px-4 py-4 sm:px-5 lg:flex-row lg:items-end lg:justify-between lg:px-6">
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
                  <Label htmlFor="incident-source-filter">Channel</Label>
                  <Select
                    id="incident-source-filter"
                    value={sourceName}
                    placeholder={isContentSourcesLoading && sourceOptions.length === 0 ? "Loading channels..." : "All channels"}
                    options={sourceOptions}
                    searchable
                    searchPlaceholder="Search channels"
                    className="w-full min-w-0"
                    disabled={isContentSourcesLoading && sourceOptions.length === 0}
                    onChange={(value) => updateParam("source_name", value)}
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
                <div className="space-y-2 xl:col-span-1">
                  <Label htmlFor="incident-sort-order">Date order</Label>
                  <Select
                    id="incident-sort-order"
                    value={sortOrder}
                    options={dateSortOptions}
                    placeholder="Newest to oldest"
                    className="w-full"
                    onChange={(value) => updateParam("sort_order", value || "newest")}
                  />
                </div>
                <div className="space-y-2 xl:col-span-1">
                  <Label htmlFor="incident-page-size">Rows per page</Label>
                  <Select
                    id="incident-page-size"
                    value={String(pageSize)}
                    options={pageSizeOptions}
                    placeholder="150 per page"
                    className="w-full"
                    onChange={(value) => {
                      updateParam(
                        "page_size",
                        value === String(DEFAULT_PAGE_SIZE) ? "" : value,
                      );
                    }}
                  />
                </div>
              </div>
              <div className="mt-6 flex flex-col gap-3 rounded-2xl border border-border bg-surface p-3 sm:p-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                  <label className="flex min-h-[3rem] w-full items-center gap-3 rounded-xl border border-border bg-surface-raised px-3.5 py-2.5 text-small font-semibold text-text-primary shadow-[0_1px_2px_rgba(11,34,54,0.04)] transition-colors hover:border-input-border-hover hover:bg-surface sm:w-auto">
                    <input
                      type="checkbox"
                      checked={hasCasualties}
                      onChange={(event) =>
                        updateParam(
                          "has_casualties",
                          event.target.checked ? "true" : "",
                        )
                      }
                      className="h-4 w-4 rounded border-border text-accent focus:ring-focus-ring"
                    />
                    <span className="leading-5">Show only incidents with casualties</span>
                  </label>
                  {hasFilters ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-11 w-full rounded-xl px-4 sm:w-auto"
                      onClick={() => {
                        const next = new URLSearchParams();
                        next.set("event_date_from", DEFAULT_EVENT_DATE_FROM);
                        next.set("event_date_to", getBeirutDate());
                        if (pageSize !== DEFAULT_PAGE_SIZE) {
                          next.set("page_size", String(pageSize));
                        }
                        setCursorHistory([]);
                        setParams(next);
                      }}
                    >
                      Clear filters
                    </Button>
                  ) : null}
                </div>
                {hasFilters ? <StatusBadge label="Filters active" variant="neutral" /> : null}
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
              getRowKey={(row) => row.id ?? `raw-${row.raw_message_id}`}
              loading={isLoading}
              error={isError}
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
                <div className="flex flex-nowrap justify-end gap-2">
                {row.id && row.verification_status === "needs_verification" ? (
                  row.duplicate_flag === "possible" ? (
                    <Button
                      type="button"
                      className="h-9 whitespace-nowrap"
                      onClick={() => navigate(`${roleBase}/incidents/${row.id}${location.search}`)}
                    >
                      Resolve duplicate
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      className="h-9"
                      onClick={() => { setReviewError(""); setReviewRow(row); }}
                    >
                      Review
                    </Button>
                  )
                ) : null}
                <Button
                  type="button"
                  variant="secondary"
                  className="h-9 whitespace-nowrap"
                  disabled={!row.id}
                  onClick={() => {
                    if (row.id) {
                      navigate(`${roleBase}/incidents/${row.id}${location.search}`);
                    }
                  }}
                >
                  View details
                </Button>
                </div>
              )}
            />
          </section>

          {total > pageSize ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-small text-text-muted">
                Showing {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} of {total} incidents | Page {page}
              </p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={cursorHistory.length === 0}
                  onClick={() => setCursorHistory((history) => history.slice(0, -1))}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!data?.next_cursor}
                  onClick={() => {
                    const nextCursor = data?.next_cursor;
                    if (nextCursor) {
                      setCursorHistory((history) => [...history, nextCursor]);
                    }
                  }}
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
                    setCursorHistory([]);
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

          {reviewRow ? (
            <Dialog title="Review incident" eyebrow="Human verification" onClose={() => !isReviewing && setReviewRow(null)}>
              <form className="space-y-4" onSubmit={async (event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                const decision = String(form.get("decision")) as "verified" | "rejected";
                const reason = String(form.get("reason") ?? "").trim() || null;
                if (decision === "rejected" && !reason) { setReviewError("A rejection reason is required."); return; }
                if (!reviewRow.id) return;
                setIsReviewing(true); setReviewError("");
                try { await reviewIncident(reviewRow.id, decision, reason, reviewRow.version); setReviewRow(null); await refetch(); }
                catch (error) { setReviewError(isAxiosError(error) && typeof error.response?.data?.detail === "string" ? error.response.data.detail : "Could not save this review."); }
                finally { setIsReviewing(false); }
              }}>
                <p className="text-small text-text-muted" dir="auto">{reviewRow.khabar}</p>
                <div className="space-y-2"><Label htmlFor="review-decision">Decision</Label><Select id="review-decision" name="decision" defaultValue="verified" placeholder="Select decision" options={[{ value: "verified", label: "Verify" }, { value: "rejected", label: "Reject" }]} /></div>
                <div className="space-y-2"><Label htmlFor="review-reason">Review note / rejection reason</Label><textarea id="review-reason" name="reason" className="min-h-24 w-full rounded-md border border-input-border bg-input-bg px-3 py-2" placeholder="Explain the decision (required for rejection)" /></div>
                {reviewError ? <p className="text-small text-danger">{reviewError}</p> : null}
                <div className="flex justify-end gap-2"><Button type="button" variant="secondary" disabled={isReviewing} onClick={() => setReviewRow(null)}>Cancel</Button><Button type="submit" isLoading={isReviewing}>Save review</Button></div>
              </form>
            </Dialog>
          ) : null}

          {/* Filtered News — Related to Incidents */}
          <section className="space-y-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <p className="text-caption font-semibold uppercase tracking-[0.14em] text-text-muted">
                  Filtered news
                </p>
                <h2 className="text-h4 font-semibold text-text-primary">Filtered News (Related to Incidents)</h2>
                <p className="max-w-3xl text-small leading-6 text-text-muted">
                  All filtered news saved in the database, ordered chronologically day by day and hour by hour with direct linkage to incidents.
                </p>
              </div>
              <span className="inline-flex items-center rounded-full bg-accent/10 px-3 py-1 text-small font-semibold text-accent">
                Related to incidents only
              </span>
            </div>

            <section className="grid gap-4 rounded-lg border border-border bg-surface-raised p-4 shadow-[0_1px_2px_rgba(11,34,54,0.04)] md:grid-cols-5">
              <div className="space-y-2">
                <Label htmlFor="filtered-from">From Date</Label>
                <Input id="filtered-from" type="date" value={newsDateFrom} onChange={(event) => { setNewsDateFrom(event.target.value); setNewsPage(1); }} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="filtered-to">To Date</Label>
                <Input id="filtered-to" type="date" value={newsDateTo} onChange={(event) => { setNewsDateTo(event.target.value); setNewsPage(1); }} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="filtered-source">Source</Label>
                <Select
                  id="filtered-source"
                  value={newsSourceName}
                  placeholder="All sources"
                  options={newsSourceOptions}
                  onChange={(value) => { setNewsSourceName(value); setNewsPage(1); }}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="filtered-status">Status</Label>
                <Select
                  id="filtered-status"
                  value={newsStatus}
                  placeholder="All statuses"
                  options={[
                    { value: "parsed", label: "Parsed" },
                    { value: "materialized", label: "Materialized" },
                    { value: "duplicate", label: "Duplicate" },
                    { value: "error", label: "Error" },
                  ]}
                  onChange={(value) => { setNewsStatus(value); setNewsPage(1); }}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="filtered-search">Search</Label>
                <Input id="filtered-search" value={newsSearch} placeholder="Text, village, or ID" onChange={(event) => { setNewsSearch(event.target.value); setNewsPage(1); }} />
              </div>
            </section>

            <DataTable
              columns={newsColumns}
              rows={newsRows}
              getRowKey={(row) => String(row.id)}
              minWidth="1180px"
              clientSort={false}
              loading={newsQuery.isLoading}
              error={newsQuery.isError}
              emptyState={<EmptyState title="No filtered news found" description="Try adjusting your date range or filters." />}
              errorState={<EmptyState title="Could not load filtered news" description="Check API connection and try again." />}
              actions={(row) => (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!row.incident_id}
                  onClick={() => {
                    if (row.incident_id) navigate(`${roleBase}/incidents/${row.incident_id}${location.search}`);
                  }}
                >
                  Open incident
                </Button>
              )}
            />

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-small text-text-muted">
                Showing {newsRows.length} of {newsTotal} filtered news items · Page {newsPage} of {newsTotalPages}
              </p>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={newsPage <= 1} onClick={() => setNewsPage(newsPage - 1)}>Previous</Button>
                <Button variant="secondary" disabled={newsPage >= newsTotalPages} onClick={() => setNewsPage(newsPage + 1)}>Next</Button>
              </div>
            </div>

            <p className="text-caption text-text-muted">
              Last loaded at {formatDateTime(new Date())}.
            </p>
          </section>
        </>
    </div>
  );
};
