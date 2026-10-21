import type { GeoCollection } from "./api";
import type { Level } from "./types";

export type Bounds = [[number, number], [number, number]];
export const LEBANON_BOUNDS: Bounds = [[35.05, 33.03], [36.65, 34.7]];

const walk = (coords: unknown, visit: (lon: number, lat: number) => void): void => {
  if (!Array.isArray(coords)) return;
  if (typeof coords[0] === "number") {
    visit(coords[0] as number, coords[1] as number);
    return;
  }
  coords.forEach((c) => walk(c, visit));
};

export const geometryBounds = (geometry: unknown): Bounds | null => {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  walk((geometry as { coordinates?: unknown } | null)?.coordinates, (x, y) => {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  });
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null;
};

export type AreaName = { code: string; level: Level; name_en: string; name_ar: string; parent: string | null };

export const buildNameIndex = (geo: Record<Level, GeoCollection>): Map<string, AreaName> => {
  const index = new Map<string, AreaName>();
  (["mohafaza", "caza", "village"] as Level[]).forEach((level) => {
    geo[level].features.forEach((f) => {
      const p = f.properties;
      const code = String(p.code);
      index.set(code, {
        code, level, name_en: String(p.name_en ?? ""), name_ar: String(p.name_ar ?? ""),
        parent: level === "village" ? String(p.caza_code ?? "") : level === "caza" ? String(p.mohafaza_code ?? "") : null,
      });
    });
  });
  return index;
};

export const findBounds = (geo: Record<Level, GeoCollection>, code: string): { level: Level; bounds: Bounds } | null => {
  for (const level of ["village", "caza", "mohafaza"] as Level[]) {
    const feature = geo[level].features.find((f) => String(f.properties.code) === code);
    if (feature) {
      const bounds = geometryBounds(feature.geometry);
      if (bounds) return { level, bounds };
    }
  }
  return null;
};

const DIACRITICS = /[ً-ٰٟـ]/g;
/** Fold Arabic spelling variants so a search for "صور" matches "صُور", alef forms and ta marbuta. */
export const normalizeSearch = (value: string): string =>
  value
    .normalize("NFKC")
    .replace(DIACRITICS, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .toLowerCase()
    .trim();

export type SearchHit = AreaName & { lat: number | null; lon: number | null };

export const searchVillages = (geo: Record<Level, GeoCollection>, query: string, limit = 8): SearchHit[] => {
  const q = normalizeSearch(query);
  if (q.length < 2) return [];
  const starts: SearchHit[] = [];
  const contains: SearchHit[] = [];
  for (const f of geo.village.features) {
    const en = normalizeSearch(String(f.properties.name_en ?? ""));
    const ar = normalizeSearch(String(f.properties.name_ar ?? ""));
    const hit: SearchHit = {
      code: String(f.properties.code), level: "village", name_en: String(f.properties.name_en ?? ""),
      name_ar: String(f.properties.name_ar ?? ""), parent: String(f.properties.caza_code ?? ""),
      lat: (f.properties.center_lat as number) ?? null, lon: (f.properties.center_lon as number) ?? null,
    };
    if (en.startsWith(q) || ar.startsWith(q)) starts.push(hit);
    else if (en.includes(q) || ar.includes(q)) contains.push(hit);
    if (starts.length >= limit) break;
  }
  return [...starts, ...contains].slice(0, limit);
};

type Ring = number[][];

/** Signed area and centroid of a closed ring (shoelace formula, planar lon/lat). */
const ringCentroid = (ring: Ring): { area: number; x: number; y: number } => {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [x0, y0] = ring[j];
    const [x1, y1] = ring[i];
    const cross = x0 * y1 - x1 * y0;
    a += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  if (a === 0) {
    const n = ring.length || 1;
    return { area: 0, x: ring.reduce((s, p) => s + p[0], 0) / n, y: ring.reduce((s, p) => s + p[1], 0) / n };
  }
  return { area: Math.abs(a / 2), x: cx / (3 * a), y: cy / (3 * a) };
};

/** Label anchor: centroid of the outer ring of the largest polygon part. */
export const labelPoint = (geometry: unknown): [number, number] | null => {
  const g = geometry as { type?: string; coordinates?: unknown } | null;
  if (!g?.coordinates) return null;
  const polygons = (g.type === "MultiPolygon" ? g.coordinates : [g.coordinates]) as Ring[][];
  let best: { area: number; x: number; y: number } | null = null;
  for (const polygon of polygons) {
    if (!polygon?.[0]?.length) continue;
    const c = ringCentroid(polygon[0]);
    if (!best || c.area > best.area) best = c;
  }
  return best ? [best.x, best.y] : null;
};

export const labelPoints = (collection: GeoCollection): Map<string, [number, number]> => {
  const out = new Map<string, [number, number]>();
  collection.features.forEach((f) => {
    const p = labelPoint(f.geometry);
    if (p) out.set(String(f.properties.code), p);
  });
  return out;
};
