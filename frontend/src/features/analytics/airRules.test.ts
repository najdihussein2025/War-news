import { describe, expect, it } from "vitest";
import { excludedAirTypes, levelDisabledReason, nearestSupportedLevel } from "./airRules";

describe("air level rules", () => {
  it("allows every level when the metric is not breaches or no type is chosen", () => {
    expect(levelDisabledReason("village", 35, false)).toBeNull();
    expect(levelDisabledReason("village", null, true)).toBeNull();
  });

  it("disables caza and village for warplanes, with the counting rule as the reason", () => {
    expect(levelDisabledReason("mohafaza", 35, true)).toBeNull();
    expect(levelDisabledReason("caza", 35, true)).toMatch(/per mohafaza/);
    expect(levelDisabledReason("village", 35, true)).toMatch(/never split below mohafaza/);
  });

  it("disables village for drones and balloons but allows it for helicopters", () => {
    expect(levelDisabledReason("village", 36, true)).not.toBeNull();
    expect(levelDisabledReason("caza", 36, true)).toBeNull();
    expect(levelDisabledReason("village", 34, true)).not.toBeNull();
    expect(levelDisabledReason("village", 38, true)).toBeNull();
  });

  it("lists the types left out of each level", () => {
    expect(excludedAirTypes("mohafaza")).toEqual([]);
    expect(excludedAirTypes("caza")).toEqual([35]);
    expect(excludedAirTypes("village")).toEqual([34, 35, 36]);
  });

  it("moves to the nearest coarser level that supports the type", () => {
    expect(nearestSupportedLevel("village", 35)).toBe("mohafaza");
    expect(nearestSupportedLevel("village", 36)).toBe("caza");
    expect(nearestSupportedLevel("caza", 38)).toBe("caza");
  });
});
