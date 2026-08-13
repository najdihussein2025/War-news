import { StatusBadge } from "../../../components/StatusBadge";
import { Card, EmptyState } from "../../../components/ui";
import { useSourcesQuery } from "../hooks";

export const SourcesPage = () => {
  const { data: sources = [], isLoading, isError } = useSourcesQuery();

  if (isLoading) {
    return (
      <div className="grid gap-5 md:grid-cols-2">
        {Array.from({ length: 3 }).map((_, index) => (
          <Card className="h-32 p-5" key={index}>
            <div className="h-full rounded-md bg-surface-muted" />
          </Card>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <Card>
        <EmptyState
          title="Could not load sources"
          description="The sources list could not be loaded. Please try again."
        />
      </Card>
    );
  }

  if (sources.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No sources yet"
          description="No ingestion sources are configured."
        />
      </Card>
    );
  }

  return (
    <div className="grid gap-5 md:grid-cols-2">
      {sources.map((source) => (
        <Card className="p-5" key={source.id}>
          <StatusBadge label={source.type} variant="accent" />
          <h2 className="mt-3 text-h4 font-semibold text-text-primary">
            {source.name}
          </h2>
        </Card>
      ))}
    </div>
  );
};
