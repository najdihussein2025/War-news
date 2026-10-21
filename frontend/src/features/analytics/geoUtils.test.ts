import { describe, expect, it } from "vitest";
import type { GeoCollection } from "./api";
import { geometryBounds, normalizeSearch, searchVillages } from "./geoUtils";

const village = (code: string, en: string, ar: string) => ({
  type: "Feature" as const,
  properties: { code, name_en: en, name_ar: ar, caza_code: "LB63", center_lat: 33.2, center_lon: 35.2 },
  geometry: { type: "Polygon", coordinates: [[[35, 33], [36, 33], [36, 34], [35, 33]]] },
});
const geo = {
  mohafaza: { type: "FeatureCollection", features: [] },
  caza: { type: "FeatureCollection", features: [] },
  village: { type: "FeatureCollection", features: [village("1", "Qana", "قانا"), village("2", "Mansouri", "المنصوري"), village("3", "Al Qana East", "قانا الشرقية")] },
} as unknown as Record<"mohafaza" | "caza" | "village", GeoCollection>;

describe("geo utils", () => {
  it("computes bounds of nested coordinates", () => {
    expect(geometryBounds(village("1", "a", "b").geometry)).toEqual([[35, 33], [36, 34]]);
    expect(geometryBounds(null)).toBeNull();
  });

  it("folds Arabic variants", () => {
    expect(normalizeSearch("إِسرائيل")).toBe(normalizeSearch("اسرائيل"));
    expect(normalizeSearch("مدرسة")).toBe(normalizeSearch("مدرسه"));
  });

  it("searches English and Arabic, prefix matches first", () => {
    expect(searchVillages(geo, "qa").map((h) => h.code)).toEqual(["1", "3"]);
    expect(searchVillages(geo, "قانا").map((h) => h.code)).toEqual(["1", "3"]);
    expect(searchVillages(geo, "q")).toEqual([]);
  });
});
