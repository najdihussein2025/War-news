import { describe, expect, it, vi } from "vitest";
import { refreshDashboardQueries } from "./refreshQueries";

describe("refreshDashboardQueries", () => {
  it("refreshes every dashboard query", async () => {
    const queries = Array.from({ length: 8 }, () => vi.fn().mockResolvedValue({ isError: false }));
    expect(await refreshDashboardQueries(queries)).toBe(false);
    queries.forEach((query) => expect(query).toHaveBeenCalledOnce());
  });

  it("reports partial failures without stopping the other refreshes", async () => {
    const success = vi.fn().mockResolvedValue({ isError: false });
    const failure = vi.fn().mockRejectedValue(new Error("offline"));
    expect(await refreshDashboardQueries([failure, success])).toBe(true);
    expect(success).toHaveBeenCalledOnce();
  });
});
