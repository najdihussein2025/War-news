import { describe, expect, it } from "vitest";
import { matchesFilters } from "./hooks";
import type { IncidentStreamEvent } from "./types";

const event = {
  id: "i-1",
  village: "Nabatieh",
  condition: "Airstrike",
  source: "Telegram",
  event_date: "2026-09-20",
  verification_status: "auto_processed",
  duplicate_flag: "none",
  total_deaths: null,
  total_injuries: null,
} as unknown as IncidentStreamEvent;

describe("live incident stream filter", () => {
  it("does not push a streamed incident into a check-type view", () => {
    expect(matchesFilters(event, { limit: 150, verificationType: "casualty_missing_number" })).toBe(false);
    expect(matchesFilters(event, { limit: 150, verificationType: "duplicate" })).toBe(false);
  });

  it("does not push a streamed incident into a channel view", () => {
    expect(matchesFilters(event, { limit: 150, sourceName: "Some channel" })).toBe(false);
  });

  it("still prepends when the visible filters match", () => {
    expect(matchesFilters(event, { limit: 150, eventDateFrom: "2026-09-01", eventDateTo: "2026-09-28" })).toBe(true);
    expect(matchesFilters(event, { limit: 150, verificationStatus: "needs_verification" })).toBe(false);
  });

  it.each([
    { total_deaths: 1 },
    { casualty_status: "count_missing" },
    { verification_types: ["casualty_aggregate_toll"] },
  ])("includes casualty-bearing events: %o", (fields) => {
    expect(matchesFilters({ ...event, ...fields } as IncidentStreamEvent, { limit: 150, hasCasualties: true })).toBe(true);
  });

  it("excludes header-only false positives", () => {
    expect(matchesFilters({ ...event, casualty_status: "none_mentioned", verification_types: [] } as IncidentStreamEvent, { limit: 150, hasCasualties: true })).toBe(false);
  });
});
