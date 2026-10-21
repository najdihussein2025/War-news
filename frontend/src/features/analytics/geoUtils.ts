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
