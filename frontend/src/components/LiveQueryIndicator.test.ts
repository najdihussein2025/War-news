import { describe, expect, it } from "vitest";
import { formatRelativeTime } from "../lib/formatters";

describe("formatRelativeTime", () => {
  it("describes recent timestamps in the past", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(threeHoursAgo)).toMatch(/hour/i);
  });

  it("returns Never for null timestamps", () => {
    expect(formatRelativeTime(null)).toBe("Never");
  });
});
