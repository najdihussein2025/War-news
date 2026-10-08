import { useMemo } from "react";
import { cn } from "../../../lib/cn";
import { highlightSegments } from "../logic";
import type { SummaryItem } from "../types";

type Props = {
  text: string | null;
  items: SummaryItem[];
  focusedItemId?: number | null;
  onFocusItem?: (itemId: number | null) => void;
};

/** The bulletin as written (RTL), with each item's evidence span highlighted. */
export const SummaryTextView = ({ text, items, focusedItemId, onFocusItem }: Props) => {
  const segments = useMemo(() => (text ? highlightSegments(text, items) : []), [text, items]);
  if (!text) {
    return <p className="text-small text-text-muted">The original message text is not available.</p>;
  }
  return (
    <div
      className="max-h-[32rem] overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-surface p-4 text-body leading-8 text-text-primary"
      dir="rtl"
      lang="ar"
    >
      {segments.map((segment, index) =>
        segment.itemIds.length ? (
          <mark
            key={index}
            className={cn(
              "cursor-pointer rounded-sm bg-accent/15 px-0.5 text-text-primary",
              focusedItemId != null && segment.itemIds.includes(focusedItemId) && "bg-warning/30 outline outline-1 outline-warning",
            )}
            onMouseEnter={() => onFocusItem?.(segment.itemIds[0])}
            onMouseLeave={() => onFocusItem?.(null)}
          >
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </div>
  );
};
