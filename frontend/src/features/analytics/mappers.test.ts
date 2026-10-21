import { describe, expect, it } from "vitest";
import { coverageWarning, deltaView, fillDays, formatNumber, hasArabic, mapValueIndex, peakOf, playbackFrames, sparkPath } from "./mappers";
import type { TimelineResponse } from "./types";

describe("analytics data mappers", () => {
  it("formats numbers with thousands separators", () => {
    expect(formatNumber(12345)).toBe("12,345");
    expect(formatNumber(null)).toBe("–");
  });

  it("describes deltas", () => {
    expect(deltaView({ current: 12, previous: 10, delta: 2, pct: 20 })).toMatchObject({ direction: "up", text: "+2 (+20.0%)" });
    expect(deltaView({ current: 5, previous: 10, delta: -5, pct: -50 }).direction).toBe("down");
    expect(deltaView({ current: 0, previous: 0, delta: 0, pct: null })).toMatchObject({ direction: "flat", text: "0" });
  });

  it("indexes map values by code", () => {
    const index = mapValueIndex({ level: "caza", metric: "incidents", unit_note: "", unsupported_air_levels: {}, values: [{ code: "LB63", value: 4 }] });
    expect(index.get("LB63")).toBe(4);
    expect(mapValueIndex(undefined).size).toBe(0);
  });

  it("zero-fills sparse daily series", () => {
    const filled = fillDays([{ date: "2026-10-02", value: 3 }], "2026-10-01", "2026-10-03");
    expect(filled.map((p) => p.value)).toEqual([0, 3, 0]);
  });

  it("builds a sparkline path and handles empty input", () => {
    expect(sparkPath([], 100, 20)).toBe("");
    expect(sparkPath([{ date: "a", value: 1 }, { date: "b", value: 2 }], 100, 20)).toMatch(/^M0\.0,.* L100\.0,/);
  });

  it("detects Arabic text", () => {
    expect(hasArabic("صور")).toBe(true);
    expect(hasArabic("Sour")).toBe(false);
  });

  it("finds the peak bar", () => {
    const t = { total: [{ date: "a", value: 1 }, { date: "b", value: 7 }, { date: "c", value: 2 }] } as TimelineResponse;
    expect(peakOf(t)).toEqual({ index: 1, value: 7 });
    expect(peakOf({ total: [{ date: "a", value: 0 }] } as TimelineResponse)).toBeNull();
  });

  it("labels incomplete daily coverage without treating it as zero activity", () => {
    expect(coverageWarning("low")).toContain("Low message coverage");
    expect(coverageWarning("none")).toContain("No ingested messages");
    expect(coverageWarning("ok")).toBeNull();
    expect(coverageWarning("unknown")).toBeNull();
  });

  it("plays back daily for short ranges and weekly for long ones", () => {
    expect(playbackFrames("2026-10-01", "2026-10-03")).toEqual([
      { from: "2026-10-01", to: "2026-10-01" }, { from: "2026-10-02", to: "2026-10-02" }, { from: "2026-10-03", to: "2026-10-03" },
    ]);
    const long = playbackFrames("2026-01-01", "2026-10-21");
    expect(long.length).toBeLessThanOrEqual(120);
    expect(long[0]).toEqual({ from: "2026-01-01", to: "2026-01-07" });
    expect(long.at(-1)?.to).toBe("2026-10-21");
  });
});
