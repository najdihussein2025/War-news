import { describe, expect, it } from "vitest";
import { labelText, polygonLabels, CAZA_LABEL_ZOOM, VILLAGE_LABEL_ZOOM } from "./mapLabels";

describe("map label geometry", () => {
  it("anchors polygon and multipolygon names without changing their identities", () => {
    const properties = { code: "LB43", name_en: "Bent Jbeil", name_ar: "بنت جبيل" };
    const collection = polygonLabels({ type: "FeatureCollection", features: [
      { type: "Feature", properties, geometry: { type: "Polygon", coordinates: [[[35, 33], [36, 33], [36, 34], [35, 34], [35, 33]]] } },
      { type: "Feature", properties: { code: "invalid" }, geometry: null },
    ] });
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0].properties).toBe(properties);
    expect(collection.features[0].geometry).toEqual({ type: "Point", coordinates: [35.5, 33.5] });
  });
  it("uses the selected language and includes a bilingual line break", () => {
    expect(labelText("en")).toEqual(["coalesce", ["get", "name_en"], ""]);
    expect(labelText("ar")).toEqual(["coalesce", ["get", "name_ar"], ""]);
    expect(JSON.stringify(labelText("both"))).toContain('\\n');
    expect(CAZA_LABEL_ZOOM).toBeLessThan(VILLAGE_LABEL_ZOOM);
  });
});
