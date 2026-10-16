import { expect, it } from "vitest";
import { incidentEventTime } from "./incidentEventTime";

const window = { summary_window_start: "2026-10-15T21:00:00Z", summary_window_end: "2026-10-16T05:42:04Z" };
it("does not substitute a summary window for an exact attack time", () => {
  expect(incidentEventTime({ ...window, event_time: null })).toBe("Exact time not stated");
});
it("preserves independently reported exact times", () => {
  expect(incidentEventTime({ ...window, event_time: "00:58:25" })).toBe("00:58");
});
it("leaves unavailable or invalid times unknown", () => {
  expect(incidentEventTime({ event_time: null })).toBe("Exact time not stated");
  expect(incidentEventTime({ ...window, event_time: null, summary_window_start: "invalid" })).toBe("Exact time not stated");
});
