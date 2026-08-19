import { useEffect, useState } from "react";
import { formatRelativeTime } from "../lib/formatters";
import { cn } from "../lib/cn";

type LiveQueryIndicatorProps = {
  latestIncidentAt: string | null;
  isFetching: boolean;
};

export const LiveQueryIndicator = ({
  latestIncidentAt,
  isFetching,
}: LiveQueryIndicatorProps) => {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => tick((value) => value + 1), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const label = (() => {
    if (isFetching) {
      return "Updating…";
    }
    if (!latestIncidentAt) {
      return "No incidents yet";
    }
    return `Updated ${formatRelativeTime(latestIncidentAt)}`;
  })();

  return (
    <span
      className="inline-flex items-center gap-2 text-caption text-text-muted"
      role="status"
      aria-live="polite"
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          isFetching ? "animate-pulse bg-accent" : "bg-success",
        )}
        aria-hidden="true"
      />
      {label}
    </span>
  );
};
