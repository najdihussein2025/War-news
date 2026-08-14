import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
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
  useContentSourcesQuery,
  useSetSourceActiveMutation,
  useSourceDetailQuery,
  useSourcesQuery,
} from "../hooks";
import type { ContentSource, Source, SourceDetail } from "../types";

const numberFormatter = new Intl.NumberFormat();
const CONTENT_SOURCE_PAGE_SIZE = 25;

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

const SourceDetails = ({ source }: { source: SourceDetail }) => (
  <dl className="grid gap-5 sm:grid-cols-2">
    <DetailItem label="ID">{source.id}</DetailItem>
    <DetailItem label="Name">{source.name}</DetailItem>
    <DetailItem label="Type">
      <StatusBadge label={source.type} variant="accent" />
    </DetailItem>
    <DetailItem label="Status">
      <StatusBadge
        label={source.is_active ? "Active" : "Paused"}
        variant={source.is_active ? "success" : "warning"}
      />
    </DetailItem>
    <DetailItem label="External ID">{source.external_id ?? "-"}</DetailItem>
    <DetailItem label="Created At">{formatDateTime(source.created_at)}</DetailItem>
    <DetailItem label="Last Cursor">
      {source.last_cursor ? (
        <code className="break-all rounded-md bg-surface-muted px-2 py-1 text-caption">
          {source.last_cursor}
        </code>
      ) : (
        "-"
      )}
    </DetailItem>
    <DetailItem label="Last News">
      <NewsAge value={source.last_message_at} />
    </DetailItem>
    <DetailItem label="Total News">
      {numberFormatter.format(source.total_messages)}
    </DetailItem>
  </dl>
);

export const SourcesPage = () => {
  const { data: sources = [], isLoading, isError } = useSourcesQuery();
  const setActiveMutation = useSetSourceActiveMutation();
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  const selectedSource = sources.find((source) => source.id === selectedSourceId);
  const detailQuery = useSourceDetailQuery(selectedSourceId);
  const [selectedPlatform, setSelectedPlatform] = useState<string | null>(null);
  const [contentSearch, setContentSearch] = useState("");
  const [contentPage, setContentPage] = useState(1);
  const debouncedContentSearch = useDebounce(contentSearch.trim(), 300);
  const allContentSourcesQuery = useContentSourcesQuery();
  const contentSourcesQuery = useContentSourcesQuery({
    platform: selectedPlatform,
    search: debouncedContentSearch,
  });

  const platformOptions = useMemo(
    () =>
      Array.from(
        new Set(
          (allContentSourcesQuery.data ?? []).map(
            (contentSource) => contentSource.source_platform,
          ),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [allContentSourcesQuery.data],
  );

  const contentSources = contentSourcesQuery.data ?? [];
  const totalContentPages = Math.max(
    1,
    Math.ceil(contentSources.length / CONTENT_SOURCE_PAGE_SIZE),
  );
  const paginatedContentSources = contentSources.slice(
    (contentPage - 1) * CONTENT_SOURCE_PAGE_SIZE,
    contentPage * CONTENT_SOURCE_PAGE_SIZE,
  );

  const closeDetails = useCallback(() => setSelectedSourceId(null), []);

  useEffect(() => {
    setContentPage(1);
  }, [selectedPlatform, debouncedContentSearch]);

  useEffect(() => {
    if (contentPage > totalContentPages) {
      setContentPage(totalContentPages);
    }
  }, [contentPage, totalContentPages]);

  const columns: Array<DataTableColumn<Source>> = [
    {
      key: "name",
      header: "Name",
      render: (source) => (
        <span className="font-semibold text-text-primary">{source.name}</span>
      ),
      sortValue: (source) => source.name,
    },
    {
      key: "type",
      header: "Type",
      render: (source) => <StatusBadge label={source.type} variant="accent" />,
      sortValue: (source) => source.type,
    },
    {
      key: "status",
      header: "Status",
      render: (source) => {
        const isThisSourceUpdating =
          setActiveMutation.isPending && setActiveMutation.variables?.sourceId === source.id;

        return (
          <div className="flex items-center gap-2">
            <StatusBadge
              label={source.is_active ? "Active" : "Paused"}
              variant={source.is_active ? "success" : "warning"}
            />
            <Button
              type="button"
              variant="secondary"
              className="h-8 px-3"
              disabled={setActiveMutation.isPending && !isThisSourceUpdating}
              isLoading={isThisSourceUpdating}
              loadingText={source.is_active ? "Pausing" : "Resuming"}
              onClick={() =>
                setActiveMutation.mutate({
                  sourceId: source.id,
                  isActive: !source.is_active,
                })
              }
            >
              {source.is_active ? "Pause" : "Resume"}
            </Button>
          </div>
        );
      },
      sortValue: (source) => source.is_active,
    },
    {
      key: "last-news",
      header: "Last News",
      render: (source) => <NewsAge value={source.last_message_at} />,
      sortValue: (source) =>
        source.last_message_at ? new Date(source.last_message_at).getTime() : 0,
    },
    {
      key: "total-news",
      header: "Total News",
      className: "text-right tabular-nums",
      render: (source) => numberFormatter.format(source.total_messages),
      sortValue: (source) => source.total_messages,
    },
  ];

  const contentColumns: Array<DataTableColumn<ContentSource>> = [
    {
      key: "source-name",
      header: "Source Name",
      render: (contentSource) => (
        <span className="font-semibold text-text-primary">
          {contentSource.source_name}
        </span>
      ),
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
    },
    {
      key: "total-news",
      header: "Total News",
      className: "text-right tabular-nums",
      render: (contentSource) => numberFormatter.format(contentSource.message_count),
    },
    {
      key: "last-news",
      header: "Last News",
      render: (contentSource) => <NewsAge value={contentSource.last_seen} />,
    },
  ];

  return (
    <>
      <div className="space-y-8">
        <section>
          {setActiveMutation.isError ? (
            <p className="mb-4 text-small font-medium text-danger" role="alert">
              The source status could not be updated. Its previous status has been restored.
            </p>
          ) : null}

          <DataTable
            columns={columns}
            rows={sources}
            getRowKey={(source) => String(source.id)}
            minWidth="880px"
            loading={isLoading}
            error={isError}
            emptyState={
              <EmptyState
                title="No sources yet"
                description="No ingestion sources are configured."
              />
            }
            errorState={
              <EmptyState
                title="Could not load sources"
                description="The sources list could not be loaded. Please try again."
              />
            }
            actions={(source) => (
              <Button
                type="button"
                variant="secondary"
                className="h-9 whitespace-nowrap"
                onClick={() => setSelectedSourceId(source.id)}
              >
                View Details
              </Button>
            )}
          />
        </section>

        <section className="space-y-4">
          <div>
            <h2 className="text-title font-semibold text-text-primary">
              Content Sources
            </h2>
            <p className="mt-1 text-small text-text-muted">
              Upstream accounts found in CNRS raw messages.
            </p>
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant={selectedPlatform === null ? "primary" : "secondary"}
                className="h-9 px-3"
                onClick={() => setSelectedPlatform(null)}
              >
                All
              </Button>
              {platformOptions.map((platform) => (
                <Button
                  type="button"
                  variant={selectedPlatform === platform ? "primary" : "secondary"}
                  className="h-9 px-3"
                  key={platform}
                  onClick={() => setSelectedPlatform(platform)}
                >
                  {formatPlatform(platform)}
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

          <DataTable
            columns={contentColumns}
            rows={paginatedContentSources}
            getRowKey={(contentSource) =>
              `${contentSource.source_platform}:${contentSource.source_name}`
            }
            minWidth="760px"
            loading={contentSourcesQuery.isLoading}
            error={contentSourcesQuery.isError}
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
      </div>

      {selectedSourceId !== null ? (
        <Dialog
          title={selectedSource?.name ?? "Source Details"}
          onClose={closeDetails}
          size="lg"
        >
          {detailQuery.isLoading ? (
            <div className="grid gap-5 sm:grid-cols-2" aria-label="Loading source details">
              {Array.from({ length: 8 }).map((_, index) => (
                <div className="h-12 rounded-md bg-surface-muted" key={index} />
              ))}
            </div>
          ) : detailQuery.isError ? (
            <div className="space-y-4">
              <EmptyState
                title="Could not load source details"
                description="The source detail could not be loaded. Please try again."
              />
              <div className="flex justify-end">
                <Button type="button" variant="secondary" onClick={() => detailQuery.refetch()}>
                  Try Again
                </Button>
              </div>
            </div>
          ) : detailQuery.data ? (
            <SourceDetails source={detailQuery.data} />
          ) : null}
        </Dialog>
      ) : null}
    </>
  );
};
