import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SummaryOriginBadge } from "./SummaryOriginBadge";
import { SummaryTextView } from "./SummaryTextView";
import { draftToAction } from "./SummaryResolveForm";
import type { SummaryItem } from "../types";

const item = (overrides: Partial<SummaryItem> = {}): SummaryItem => ({
  id: 7,
  position: 0,
  header_text: "الغارات",
  condition: { id: 46, name_en: "Bombs", name_ar: "قصف وغارات" },
  location_text: "قرية جديدة",
  primary_village: null,
  secondary_village: null,
  modifier: "none",
  reported_count: 1,
  evidence_span: "- قرية جديدة",
  origin: "parser",
  resolution: "unresolved_location",
  reconciliation_status: "pending",
  display_status: "unresolved",
  reason_type: "unresolved_location",
  matched_incident_id: null,
  created_incident_id: null,
  ...overrides,
});

const draft = (change: Partial<Parameters<typeof draftToAction>[2]> = {}) => ({
  mode: "" as const,
  villageId: "",
  conditionIds: [""],
  save: false,
  ...change,
});

describe("SummaryOriginBadge", () => {
  it("renders the badge with a link and tooltip for summary-origin incidents", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <SummaryOriginBadge origin="summary" summaryId={12} channel="قناة" windowEnd="2026-10-08T00:00:00Z" roleBase="/admin" />
      </MemoryRouter>,
    );
    expect(html).toContain("من الملخص");
    expect(html).toContain('href="/admin/incidents?verification_type=summary_review&amp;summary_id=12"');
    expect(html).toContain("Created from a summary bulletin");
  });

  it("renders nothing for live incidents", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <SummaryOriginBadge origin="live" summaryId={null} roleBase="/admin" />
      </MemoryRouter>,
    );
    expect(html).toBe("");
  });
});

describe("SummaryTextView", () => {
  it("highlights evidence spans in an RTL block", () => {
    const html = renderToStaticMarkup(
      <SummaryTextView text={"الغارات:\n- قرية جديدة"} items={[item()]} />,
    );
    expect(html).toContain('dir="rtl"');
    expect(html).toContain("<mark");
    expect(html).toContain("- قرية جديدة");
  });

  it("explains when the text is missing", () => {
    expect(renderToStaticMarkup(<SummaryTextView text={null} items={[]} />)).toContain("not available");
  });
});

describe("draftToAction", () => {
  it("needs a village for an unresolved location and passes the alias flag", () => {
    expect(draftToAction(item(), "unresolved_location", draft({ mode: "resolve" }))).toBeNull();
    expect(draftToAction(item(), "unresolved_location", draft({ mode: "resolve", villageId: "5", save: true }))).toEqual({
      item_id: 7, action: "resolve", village_id: 5, save_alias: true,
    });
  });

  it("asks for the section action when the item has none", () => {
    const noCondition = item({ condition: null });
    expect(draftToAction(noCondition, "unresolved_location", draft({ mode: "resolve", villageId: "5" }))).toBeNull();
    expect(draftToAction(noCondition, "unresolved_location", draft({ mode: "resolve", villageId: "5", conditionIds: ["9"] }))).toMatchObject({
      condition_ids: [9],
    });
  });

  it("maps an unknown header to condition ids and the mapping flag", () => {
    expect(draftToAction(item(), "unknown_header", draft({ mode: "resolve" }))).toBeNull();
    expect(draftToAction(item(), "unknown_header", draft({ mode: "resolve", conditionIds: ["9", "7", ""], save: true }))).toEqual({
      item_id: 7, action: "resolve", condition_ids: [9, 7], save_mapping: true,
    });
  });

  it("handles casualty wording and dismissal", () => {
    expect(draftToAction(item(), "casualty_in_summary", draft())).toBeNull();
    expect(draftToAction(item(), "casualty_in_summary", draft({ mode: "create_incident" }))).toEqual({ item_id: 7, action: "create_incident" });
    expect(draftToAction(item(), "unknown_header", draft({ mode: "dismiss" }))).toEqual({ item_id: 7, action: "dismiss" });
  });
});
