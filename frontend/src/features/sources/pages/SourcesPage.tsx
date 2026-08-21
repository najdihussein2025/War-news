import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { StatusBadge } from "../../../components/StatusBadge";
import {
  Button,
  DataTable,
  Dialog,
  EmptyState,
  Input,
  type DataTableColumn,
} from "../../../components/ui";
import { useDebounce } from "../../../hooks/useDebounce";
import { formatDateTime } from "../../../lib/formatters";
import {
  useContentSourceDetailQuery,
  useContentSourcesQuery,
  useSetContentSourceBlockedMutation,
} from "../hooks";
import type { ContentSource, ContentSourceDetail } from "../types";

const numberFormatter = new Intl.NumberFormat();
const CONTENT_SOURCE_PAGE_SIZE = 50;
const GENERIC_SOURCE_NAME = "CNRS Webhook";
type SourceFilter = "all" | "active" | "paused";

const getFreshness = (lastSeen: string) => {
  const ageHours = (Date.now() - new Date(lastSeen).getTime()) / 3_600_000;
  if (ageHours <= 24) return { label: "Live", variant: "success" as const };
  if (ageHours <= 168) return { label: "Stale", variant: "warning" as const };
  return { label: "Offline", variant: "danger" as const };
};

const formatNewsAge = (value: string | null) => {
  if (!value) {
    return "-";
  }

  const elapsedSeconds = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 1000),
  );
  if (elapsedSeconds < 60) {
    return "Just now";
  }

  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) {
    return `${elapsedMinutes}m ago`;
  }

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `${elapsedHours}h ago`;
  }

  const elapsedDays = Math.floor(elapsedHours / 24);
  if (elapsedDays < 30) {
    return `${elapsedDays}d ago`;
  }

  const elapsedMonths = Math.floor(elapsedDays / 30);
  if (elapsedMonths < 12) {
    return `${elapsedMonths}mo ago`;
  }

  return `${Math.floor(elapsedMonths / 12)}y ago`;
};

const formatPlatform = (platform: string) =>
  platform.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

const NewsAge = ({ value }: { value: string | null }) => (
  <span className="text-text-muted" title={value ? formatDateTime(value) : undefined}>
    {formatNewsAge(value)}
  </span>
);

const DetailItem = ({ label, children }: { label: string; children: ReactNode }) => (
  <div>
    <dt className="text-caption font-semibold uppercase text-text-muted">{label}</dt>
    <dd className="mt-1 text-small text-text-primary">{children}</dd>
  </div>
);

const ContentSourceStatus = ({ isBlocked }: { isBlocked: boolean }) => (
  <StatusBadge
    label={isBlocked ? "Paused" : "Active"}
    variant={isBlocked ? "warning" : "success"}
  />
);

const MessageSnippet = ({ text }: { text: string | null }) => {
  if (!text?.trim()) {
    return <span className="text-text-muted">No text</span>;
  }

  const normalized = text.replace(/\s+/g, " ").trim();
  return (
    <span>
      {normalized.length > 180 ? `${normalized.slice(0, 180)}...` : normalized}
    </span>
  );
};

const ContentSourceDetails = ({ detail }: { detail: ContentSourceDetail }) => {
  const blockMutation = useSetContentSourceBlockedMutation();

  return (
  <div className="space-y-6">
    <dl className="grid gap-5 sm:grid-cols-2">
      <DetailItem label="Source Name">{detail.source_name}</DetailItem>
      <DetailItem label="Platform">
        <StatusBadge label={formatPlatform(detail.source_platform)} variant="accent" />
      </DetailItem>
      <DetailItem label="Status">
        <div className="flex flex-wrap items-center gap-2">
          <ContentSourceStatus isBlocked={detail.is_blocked} />
          <Button
            type="button"
            variant="secondary"
            className="h-8 px-3"
            isLoading={blockMutation.isPending}
            loadingText={detail.is_blocked ? "Resuming" : "Pausing"}
            onClick={() =>
              blockMutation.mutate({
                sourcePlatform: detail.source_platform,
                originAccount: detail.origin_account,
                isBlocked: !detail.is_blocked,
              })
            }
          >
            {detail.is_blocked ? "Resume" : "Pause"}
          </Button>
        </div>
      </DetailItem>
      <DetailItem label="Origin Account">{detail.origin_account}</DetailItem>
      <DetailItem label="Total News">
        {numberFormatter.format(detail.message_count)}
      </DetailItem>
      <DetailItem label="First Seen">{formatDateTime(detail.first_seen)}</DetailItem>
      <DetailItem label="Last News Sent">
        <NewsAge value={detail.last_seen} />
      </DetailItem>
    </dl>

    <div>
      <h3 className="text-small font-semibold uppercase text-text-muted">
        Recent Raw Messages
      </h3>
      {detail.recent_messages.length > 0 ? (
        <ol className="mt-3 space-y-3">
          {detail.recent_messages.slice(0, 3).map((message) => (
            <li
              className="rounded-md border border-border bg-surface px-3 py-3"
              key={message.id}
            >
              <p className="text-small text-text-primary">
                <MessageSnippet text={message.raw_text} />
              </p>
              <p className="mt-2 text-caption text-text-muted">
                {formatDateTime(message.message_datetime ?? message.received_at)}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-small text-text-muted">No recent messages found.</p>
      )}
    </div>
  </div>
  );
};

export const SourcesPage = () => {
  const [selectedPlatform, setSelectedPlatform] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<SourceFilter>("all");
  const [contentSearch, setContentSearch] = useState("");
  const [contentPage, setContentPage] = useState(1);
  const [selectedContentSource, setSelectedContentSource] =
    useState<ContentSource | null>(null);
  const debouncedContentSearch = useDebounce(contentSearch.trim(), 300);
  const allContentSourcesQuery = useContentSourcesQuery();
  const contentSourcesQuery = useContentSourcesQuery({
    platform: selectedPlatform,
    search: debouncedContentSearch,
  });
  const detailQuery = useContentSourceDetailQuery(
    selectedContentSource?.source_platform ?? null,
    selectedContentSource?.origin_account ?? null,
  );
  const allContentSources = useMemo(
    () =>
      (allContentSourcesQuery.data ?? []).filter(
        (contentSource) => contentSource.source_name !== GENERIC_SOURCE_NAME,
      ),
    [allContentSourcesQuery.data],
  );

  const platformOptions = useMemo(
    () =>
      Array.from(
        new Set(
          allContentSources.map((contentSource) => contentSource.source_platform),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [allContentSources],
  );

  const platformCounts = useMemo(
    () =>
      Object.fromEntries(
        platformOptions.map((platform) => [
          platform,
          allContentSources.filter((source) => source.source_platform === platform).length,
        ]),
      ),
    [allContentSources, platformOptions],
  );

  const summary = useMemo(() => ({
    total: allContentSources.length,
    active: allContentSources.filter((source) => !source.is_blocked).length,
    paused: allContentSources.filter((source) => source.is_blocked).length,
    reporting: allContentSources.filter((source) => getFreshness(source.last_seen).label === "Live").length,
  }), [allContentSources]);

  const contentSources = useMemo(
    () =>
      (contentSourcesQuery.data ?? []).filter(
        (contentSource) => contentSource.source_name !== GENERIC_SOURCE_NAME,
      ).filter((contentSource) => {
        if (selectedStatus === "active") return !contentSource.is_blocked;
        if (selectedStatus === "paused") return contentSource.is_blocked;
        return true;
      }).sort(
        (a, b) => new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime(),
      ),
    [contentSourcesQuery.data, selectedStatus],
  );
  const totalContentPages = Math.max(
    1,
    Math.ceil(contentSources.length / CONTENT_SOURCE_PAGE_SIZE),
  );
  const paginatedContentSources = contentSources.slice(
    (contentPage - 1) * CONTENT_SOURCE_PAGE_SIZE,
    contentPage * CONTENT_SOURCE_PAGE_SIZE,
  );

  const closeDetails = useCallback(() => setSelectedContentSource(null), []);

  useEffect(() => {
    setContentPage(1);
  }, [selectedPlatform, selectedStatus, debouncedContentSearch]);

  useEffect(() => {
    if (contentPage > totalContentPages) {
      setContentPage(totalContentPages);
    }
  }, [contentPage, totalContentPages]);

  const contentColumns: Array<DataTableColumn<ContentSource>> = [
    {
      key: "number",
      header: "Order",
      className: "w-16 tabular-nums text-text-muted",
      render: (_contentSource, rowIndex) =>
        numberFormatter.format(
          (contentPage - 1) * CONTENT_SOURCE_PAGE_SIZE
            + rowIndex
            + 1,
        ),
    },
    {
      key: "source-name",
      header: "Source Name",
      render: (contentSource) => (
        <span className="font-semibold text-text-primary">
          {contentSource.source_name}
        </span>
      ),
      sortValue: (contentSource) => contentSource.source_name,
    },
    {
      key: "platform",
      header: "Platform",
      render: (contentSource) => (
        <StatusBadge
          label={formatPlatform(contentSource.source_platform)}
          variant="accent"
        />
      ),
      sortValue: (contentSource) => contentSource.source_platform,
    },
    {
      key: "status",
      header: "Status",
      render: (contentSource) => <ContentSourceStatus isBlocked={contentSource.is_blocked} />,
      sortValue: (contentSource) => contentSource.is_blocked,
    },
    {
      key: "total-news",
      header: "Total News",
      className: "text-right tabular-nums",
      render: (contentSource) => numberFormatter.format(contentSource.message_count),
      sortValue: (contentSource) => contentSource.message_count,
    },
    {
      key: "last-news",
      header: "Last News Sent",
      render: (contentSource) => <NewsAge value={contentSource.last_seen} />,
      sortValue: (contentSource) => new Date(contentSource.last_seen).getTime(),
    },
  ];

  return (
    <>
      <section className="space-y-4">
        <div>
          <h2 className="text-title font-semibold text-text-primary">
            Content Sources
          </h2>
          <p className="mt-1 text-small text-text-muted">
            Upstream accounts found in CNRS raw messages.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[
            ["Total sources", summary.total],
            ["Active", summary.active],
            ["Paused", summary.paused],
          ].map(([label, value]) => (
            <div className="rounded-lg border border-border bg-surface-raised px-4 py-3" key={label}>
              <p className="text-caption font-semibold uppercase text-text-muted">{label}</p>
              <p className="mt-1 text-h3 font-semibold tabular-nums text-text-primary">{numberFormatter.format(Number(value))}</p>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={selectedPlatform === null ? "primary" : "secondary"}
              className="h-9 px-3"
              onClick={() => setSelectedPlatform(null)}
            >
              All ({numberFormatter.format(allContentSources.length)})
            </Button>
            {platformOptions.map((platform) => (
              <Button
                type="button"
                variant={selectedPlatform === platform ? "primary" : "secondary"}
                className="h-9 px-3"
                key={platform}
                onClick={() => setSelectedPlatform(platform)}
              >
                {formatPlatform(platform)} ({numberFormatter.format(platformCounts[platform] ?? 0)})
              </Button>
            ))}
          </div>
          <Input
            aria-label="Search content source name"
            className="h-10 lg:w-80"
            placeholder="Search source name"
            value={contentSearch}
            onChange={(event) => setContentSearch(event.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" aria-label="Filter sources by status">
            {(["all", "active", "paused"] as SourceFilter[]).map((status) => (
              <Button
                type="button"
                variant={selectedStatus === status ? "primary" : "secondary"}
                className="h-8 px-3 capitalize"
                key={status}
                onClick={() => setSelectedStatus(status)}
              >
                {status}
              </Button>
            ))}
          </div>
          <p className="text-small text-text-muted">
            {numberFormatter.format(contentSources.length)} matching source{contentSources.length === 1 ? "" : "s"}
          </p>
        </div>

        <DataTable
          columns={contentColumns}
          rows={paginatedContentSources}
          initialSort={{ key: "last-news", direction: "desc" }}
          getRowKey={(contentSource) =>
            `${contentSource.source_platform}:${contentSource.origin_account}`
          }
          minWidth="980px"
          loading={contentSourcesQuery.isLoading}
          error={contentSourcesQuery.isError}
          onRowClick={setSelectedContentSource}
          emptyState={
            <EmptyState
              title="No content sources found"
              description="No upstream accounts match the current filters."
            />
          }
          errorState={
            <EmptyState
              title="Could not load content sources"
              description="The content sources list could not be loaded. Please try again."
            />
          }
          actions={(contentSource) => (
            <Button
              type="button"
              variant="secondary"
              className="h-9 whitespace-nowrap"
              onClick={() => setSelectedContentSource(contentSource)}
            >
              View Details
            </Button>
          )}
        />

        {!contentSourcesQuery.isLoading &&
        !contentSourcesQuery.isError &&
        contentSources.length > 0 ? (
          <div className="flex flex-col gap-3 text-small text-text-muted sm:flex-row sm:items-center sm:justify-between">
            <span>
              Showing{" "}
              {numberFormatter.format(
                (contentPage - 1) * CONTENT_SOURCE_PAGE_SIZE + 1,
              )}
              {"-"}
              {numberFormatter.format(
                Math.min(
                  contentPage * CONTENT_SOURCE_PAGE_SIZE,
                  contentSources.length,
                ),
              )}{" "}
              of {numberFormatter.format(contentSources.length)}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                className="h-9 px-3"
                disabled={contentPage === 1}
                onClick={() => setContentPage((page) => Math.max(1, page - 1))}
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="h-9 px-3"
                disabled={contentPage === totalContentPages}
                onClick={() =>
                  setContentPage((page) => Math.min(totalContentPages, page + 1))
                }
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      {selectedContentSource !== null ? (
        <Dialog
          title={selectedContentSource.source_name}
          onClose={closeDetails}
          size="lg"
        >
          {detailQuery.isLoading ? (
            <div
              className="grid gap-5 sm:grid-cols-2"
              aria-label="Loading content source details"
            >
              {Array.from({ length: 7 }).map((_, index) => (
                <div className="h-12 rounded-md bg-surface-muted" key={index} />
              ))}
            </div>
          ) : detailQuery.isError ? (
            <div className="space-y-4">
              <EmptyState
                title="Could not load content source details"
                description="The content source detail could not be loaded. Please try again."
              />
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => detailQuery.refetch()}
                >
                  Try Again
                </Button>
              </div>
            </div>
          ) : detailQuery.data ? (
            <ContentSourceDetails detail={detailQuery.data} />
          ) : null}
        </Dialog>
      ) : null}
    </>
  );
};
