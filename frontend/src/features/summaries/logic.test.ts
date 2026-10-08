import { describe, expect, it } from "vitest";
import { highlightSegments, openReviewItemIds, reasonLabel, statusVariant } from "./logic";

describe("highlightSegments", () => {
  const text = "الغارات:\n- كفرا\n- بين الخيام وميفدون";

  it("marks each evidence span and keeps the text in order", () => {
    const segments = highlightSegments(text, [
      { id: 1, evidence_span: "- كفرا" },
      { id: 2, evidence_span: "- بين الخيام وميفدون" },
    ]);
    expect(segments.map((s) => s.text).join("")).toBe(text);
    expect(segments.filter((s) => s.itemIds.length).map((s) => s.itemIds)).toEqual([[1], [2]]);
  });

  it("skips evidence that is not in the text instead of guessing", () => {
    const segments = highlightSegments(text, [{ id: 9, evidence_span: "غير موجود" }]);
    expect(segments).toEqual([{ text, itemIds: [] }]);
  });

  it("merges overlapping spans", () => {
    const segments = highlightSegments("abcdef", [
      { id: 1, evidence_span: "abcd" },
      { id: 2, evidence_span: "cdef" },
    ]);
    expect(segments).toEqual([{ text: "abcdef", itemIds: [1, 2] }]);
  });
});

describe("review helpers", () => {
  it("lists only unhandled reason items", () => {
    expect(
      openReviewItemIds([{ item_ids: [1] }, { item_ids: [2], handled: { action: "dismiss" } }, { item_ids: [3, 4] }]),
    ).toEqual([1, 3, 4]);
    expect(openReviewItemIds(undefined)).toEqual([]);
  });

  it("labels reasons and statuses", () => {
    expect(reasonLabel("unknown_header")).toBe("Unknown header");
    expect(statusVariant("matched")).toBe("success");
    expect(statusVariant("casualty")).toBe("warning");
    expect(statusVariant("pending")).toBe("neutral");
  });
});
