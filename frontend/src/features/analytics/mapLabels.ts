import type { ExpressionSpecification } from "maplibre-gl";
import type { GeoCollection } from "./api";
import { labelPoint } from "./geoUtils";

export type LabelLanguage = "en" | "ar" | "both";
export const CAZA_LABEL_ZOOM = 8.6;
export const VILLAGE_LABEL_ZOOM = 10;

export const labelText = (language: LabelLanguage): ExpressionSpecification => {
  const en: ExpressionSpecification = ["coalesce", ["get", "name_en"], ""];
  const ar: ExpressionSpecification = ["coalesce", ["get", "name_ar"], ""];
  if (language === "en") return en;
  if (language === "ar") return ar;
  return ["concat", en, ["case", ["all", ["!=", en, ""], ["!=", ar, ""]], "\n", ""], ar];
};

/** Static polygon anchors. Village anchors come exclusively from the table endpoint. */
export const polygonLabels = (collection: GeoCollection): GeoCollection => ({
  type: "FeatureCollection",
  features: collection.features.flatMap((feature) => {
    const point = labelPoint(feature.geometry);
    return point ? [{ type: "Feature" as const, properties: feature.properties,
      geometry: { type: "Point", coordinates: point } }] : [];
  }),
});
