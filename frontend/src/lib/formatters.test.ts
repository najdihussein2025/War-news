import { describe, expect, it } from "vitest";
import {
  formatClockTime,
  formatDate,
  formatDateTime,
  formatTimeGap,
} from "./formatters";

describe("formatDateTime", () => {
  it("converts UTC timestamps to Beirut local time", () => {
    expect(formatDateTime("2026-08-19T09:00:12.000Z")).toMatch(/Aug 19, 2026.*12:00/);
  });

  it("converts a late-UTC evening timestamp to the next Beirut calendar day", () => {
    expect(formatDateTime("2026-08-17T21:30:00.000Z")).toMatch(/Aug 18, 2026.*12:30/);
  });
});

describe("formatDate", () => {
  it("preserves calendar dates without shifting the day", () => {
    expect(formatDate("2026-08-19")).toMatch(/Aug 19, 2026/);
  });

  it("does not roll back a calendar date when the viewer timezone differs", () => {
    expect(formatDate("2026-08-19")).not.toMatch(/Aug 18, 2026/);
  });
});

describe("formatClockTime", () => {
  it("shows Beirut wall-clock time with seconds", () => {
    expect(formatClockTime("2026-08-19T09:00:12.000Z")).toMatch(/12:00:12/);
  });
});

describe("formatTimeGap", () => {
  it("shows minute gaps when both incidents have close event times", () => {
    expect(
      formatTimeGap(
        { event_date: "2026-09-09", event_time: "12:00:00" },
        { event_date: "2026-09-09", event_time: "12:12:00" },
      ),
    ).toBe("12 minutes apart");
  });

  it("shows hour and minute gaps when both incidents have event times", () => {
    expect(
      formatTimeGap(
        { event_date: "2026-09-09", event_time: "12:00:00" },
        { event_date: "2026-09-09", event_time: "14:30:00" },
      ),
    ).toBe("2h 30m apart");
  });

  it("shows day gaps for events more than a day apart", () => {
    expect(
      formatTimeGap(
        { event_date: "2026-09-09", event_time: "12:00:00" },
        { event_date: "2026-09-11", event_time: "13:00:00" },
      ),
    ).toBe("2 days apart");
  });

  it("falls back to date-only precision when either event time is missing", () => {
    expect(
      formatTimeGap(
        { event_date: "2026-09-09", event_time: null },
        { event_date: "2026-09-09", event_time: "12:12:00" },
      ),
    ).toBe("same day");
  });
});
