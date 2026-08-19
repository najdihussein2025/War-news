import { describe, expect, it } from "vitest";
import { formatClockTime, formatDate, formatDateTime } from "./formatters";

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
