import { useEffect, useState } from "react";
import { cn } from "../lib/cn";

type LiveQueryIndicatorProps = {
  dataUpdatedAt: number;
  isFetching: boolean;
};

export const LiveQueryIndicator = ({
  dataUpdatedAt,
  isFetching,
}: LiveQueryIndicatorProps) => {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => tick((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const secondsAgo = Math.max(0, Math.floor((Date.now() - dataUpdatedAt) / 1000));
  const label =
    isFetching && secondsAgo < 2
      ? "Updating…"
      : secondsAgo < 5
        ? "Updated just now"
        : `Updated ${secondsAgo}s ago`;

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
