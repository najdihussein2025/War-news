import { describe, expect, it } from "vitest";
import { defaultFilters, parseFilters, resolveRange, serializeFilters, toApiParams } from "./filters";

const ctx = { today: "2026-10-21", dataFirst: "2026-08-17", dataLast: "2026-10-21" };

describe("analytics URL filter state", () => {
  it("defaults to the last 30 days at mohafaza level", () => {
    const f = parseFilters(new URLSearchParams(), ctx);
    expect(f).toMatchObject({ dateFrom: "2026-09-22", dateTo: "2026-10-21", level: "mohafaza", metric: "incidents", includePending: false });
  });

  it("round-trips through the query string and omits defaults", () => {
    expect(serializeFilters(defaultFilters(ctx.today), ctx.today).toString()).toBe("");
    const f = {
      ...defaultFilters(ctx.today),
      range: "7d", dateFrom: "2026-10-15", dateTo: "2026-10-21", level: "caza" as const,
      families: ["airstrikes", "gunfire"], metric: "deaths" as const, includePending: true, areaCode: "LB63",
    };
    const qs = serializeFilters(f, ctx.today);
    expect(parseFilters(new URLSearchParams(qs.toString()), ctx)).toEqual(f);
  });

  it("falls back to defaults for malformed values", () => {
    const f = parseFilters(new URLSearchParams("level=planet&metric=money&range=custom&from=bad&to=worse&air=-4"), ctx);
    expect(f.level).toBe("mohafaza");
    expect(f.metric).toBe("incidents");
    expect(f.range).toBe("30d");
    expect(f.airType).toBeNull();
  });

  it("resolves presets, war months and clamps 'all' to 400 days", () => {
    expect(resolveRange("7d", ctx)).toEqual({ from: "2026-10-15", to: "2026-10-21" });
    expect(resolveRange("m:2026-09", ctx)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(resolveRange("m:2026-10", ctx).to).toBe("2026-10-21");
    expect(resolveRange("all", ctx)).toEqual({ from: "2026-08-17", to: "2026-10-21" });
    const old = resolveRange("all", { ...ctx, dataFirst: "2020-01-01" });
    expect((Date.parse(old.to) - Date.parse(old.from)) / 86_400_000 + 1).toBe(400);
  });

  it("builds API params, sending the air type only for breaches", () => {
    const base = { ...defaultFilters(ctx.today), families: ["gunfire"], airType: 35 };
    expect(toApiParams(base).get("condition_id")).toBeNull();
    const api = toApiParams({ ...base, metric: "breaches", includePending: true });
    expect(api.get("condition_id")).toBe("35");
    expect(api.get("include_pending")).toBe("true");
    expect(api.getAll("family")).toEqual(["gunfire"]);
  });
});
