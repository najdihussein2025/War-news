import { Link } from "react-router-dom";
import { formatDate } from "../../../lib/formatters";

type Props = {
  origin?: "live" | "summary";
  summaryId?: number | null;
  channel?: string | null;
  windowEnd?: string | null;
  roleBase: string;
};

/** Small "من الملخص" badge for incidents a summary bulletin created; the tooltip links to the summary. */
export const SummaryOriginBadge = ({ origin, summaryId, channel, windowEnd, roleBase }: Props) => {
  if (origin !== "summary") return null;
  const detail = [channel, windowEnd ? formatDate(windowEnd) : null].filter(Boolean).join(" · ");
  const title = detail ? `Created from a summary bulletin (${detail})` : "Created from a summary bulletin";
  const badge = (
    <span
      className="inline-flex items-center rounded-md border border-accent bg-surface-muted px-2 py-1 text-caption font-semibold text-accent"
      title={title}
    >
      من الملخص
    </span>
  );
  return summaryId ? (
    <Link to={`${roleBase}/summaries/${summaryId}`} aria-label={title} className="inline-flex" onClick={(event) => event.stopPropagation()}>
      {badge}
    </Link>
  ) : (
    badge
  );
};
