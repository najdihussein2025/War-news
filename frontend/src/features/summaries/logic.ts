import type { SummaryItemDisplayStatus, SummaryReasonType, SummaryStatus } from "./types";

export type TextSegment = { text: string; itemIds: number[] };

/**
 * Split the bulletin into plain and highlighted segments. Each item's evidence span is
 * a verbatim substring of the text (the backend guarantees it); an evidence that cannot
 * be found is skipped rather than guessed at. Overlapping spans are merged.
 */
export const highlightSegments = (text: string, items: Array<{ id: number; evidence_span: string }>): TextSegment[] => {
  const ranges: Array<{ start: number; end: number; ids: number[] }> = [];
  for (const item of items) {
    if (!item.evidence_span) continue;
    const start = text.indexOf(item.evidence_span);
    if (start < 0) continue;
    ranges.push({ start, end: start + item.evidence_span.length, ids: [item.id] });
  }
  ranges.sort((a, b) => a.start - b.start || b.end - a.end);
  const merged: typeof ranges = [];
  for (const range of ranges) {
    const last = merged.at(-1);
    if (last && range.start < last.end) {
      last.end = Math.max(last.end, range.end);
      last.ids.push(...range.ids);
    } else {
      merged.push({ ...range, ids: [...range.ids] });
    }
  }
  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const range of merged) {
    if (range.start > cursor) segments.push({ text: text.slice(cursor, range.start), itemIds: [] });
    segments.push({ text: text.slice(range.start, range.end), itemIds: range.ids });
    cursor = range.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), itemIds: [] });
  return segments;
};

export const reasonLabel = (type: SummaryReasonType) =>
  type === "unresolved_location" ? "Unresolved location" : type === "unknown_header" ? "Unknown header" : "Casualty wording";

export const statusLabel = (status: SummaryItemDisplayStatus) =>
  ({
    pending: "Pending",
    matched: "Matched",
    created: "Incident created",
    ambiguous: "Closed",
    unresolved: "Unresolved",
    unknown_header: "Unknown header",
    header_handled: "Header handled",
    casualty: "Casualty wording",
    dismissed: "Dismissed",
  })[status];

export const statusVariant = (status: SummaryItemDisplayStatus): "success" | "warning" | "neutral" =>
  status === "matched" || status === "created"
    ? "success"
    : status === "unresolved" || status === "unknown_header" || status === "casualty"
      ? "warning"
      : "neutral";

export const summaryStatusLabel = (status: SummaryStatus) => status.replace(/_/g, " ");

/** Item ids that still need a reviewer, in reason order. */
export const openReviewItemIds = (
  reasons: Array<{ item_ids: number[]; handled?: unknown }> | undefined,
): number[] => (reasons ?? []).filter((reason) => !reason.handled).flatMap((reason) => reason.item_ids);
