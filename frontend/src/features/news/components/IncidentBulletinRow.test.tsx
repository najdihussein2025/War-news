import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Incident, IncidentBulletinGroup } from "../types";
import {
  bulletinReasonPresentation,
  CompactIncidentList,
  IncidentBulletinActions,
  IncidentBulletinHeading,
  incidentWarningLabels,
} from "./IncidentBulletinRow";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const incident = (overrides: Partial<Incident> = {}): Incident => ({
  id: crypto.randomUUID(),
  raw_message_id: 42,
  raw_status: null,
  village: "Aita",
  condition: "Strike",
  condition_ar: null,
  event_date: "2026-10-07",
  event_time: "12:30:00",
  khabar: "خبر تجريبي",
  source: "Telegram",
  source_reference: null,
  source_name: "Test source",
  total_deaths: 0,
  total_injuries: 0,
  matched: true,
  verification_status: "needs_verification",
  verification_reason: null,
  verified_by_user_id: null,
  verified_at: null,
  duplicate_flag: "none",
  details_pending: false,
  created_at: "2026-10-07T12:30:00Z",
  version: 1,
  locked_by_user_id: null,
  edit_lock_expires_at: null,
  ...overrides,
});

const group = (overrides: Partial<IncidentBulletinGroup> = {}): IncidentBulletinGroup => ({
  raw_message_id: 42,
  khabar: "خبر تجريبي",
  source: "Telegram",
  source_name: "Test source",
  source_reference: null,
  event_date: "2026-10-07",
  event_time: "12:30:00",
  verification_reasons: ["Possible duplicate score 1.00", "Changed after verification"],
  verification_types: ["duplicate"],
  incidents: Array.from({ length: 8 }, (_, index) => incident({
    id: `incident-${index + 1}`,
    village: `Village ${index + 1}`,
    verification_reason: index === 0 ? "Low confidence village match" : null,
    total_deaths: index === 1 ? 2 : 0,
    total_injuries: index === 1 ? 1 : 0,
  })),
  ...overrides,
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("IncidentBulletinActions", () => {
  it("keeps desktop actions in Open, Reject all, Verify all order and fires each handler", () => {
    const onOpen = vi.fn();
    const onReject = vi.fn();
    const onVerify = vi.fn();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);

    act(() => root.render(
      <IncidentBulletinActions onOpen={onOpen} onReject={onReject} onVerify={onVerify} />,
    ));

    const desktopButtons = Array.from(host.querySelectorAll("div > div:first-child > button"));
    expect(desktopButtons.map((button) => button.textContent)).toEqual(["Open", "Reject all", "Verify all"]);
    desktopButtons.forEach((button) => act(() => (button as HTMLButtonElement).click()));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();
    expect(onVerify).toHaveBeenCalledOnce();
    act(() => root.unmount());
  });
});

describe("compact bulletin content", () => {
  it("shows warning dots only when an incident's reason differs from its siblings", () => {
    const mixed = group().incidents.slice(0, 3);
    expect(incidentWarningLabels(mixed)).toEqual(["Low-confidence village", "", ""]);

    const sameReason = mixed.map((item) => ({ ...item, verification_reason: "Low confidence village match" }));
    expect(incidentWarningLabels(sameReason)).toEqual(["", "", ""]);
  });

  it("renders compact casualty copy and an eight-incident expander", () => {
    const html = renderToStaticMarkup(<CompactIncidentList group={group()} />);
    expect(html).toContain("no casualties");
    expect(html).toContain("2 deaths · 1 injury");
    expect(html).toContain("+5 more incidents");
    expect(html).not.toContain("Deaths 0");
  });

  it("merges duplicate signals into one badge and keeps changed as a separate badge", () => {
    const fixture = group();
    const presentation = bulletinReasonPresentation(fixture);
    const html = renderToStaticMarkup(<IncidentBulletinHeading group={fixture} />);

    expect(presentation.duplicateLabel).toBe("Duplicate · 100%");
    expect(presentation.chips.some((chip) => chip.key === "duplicate")).toBe(false);
    expect((html.match(/Duplicate · 100%/g) ?? [])).toHaveLength(1);
    expect(html).toContain("Changed after verification");
  });
});
