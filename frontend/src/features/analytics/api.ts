import { apiClient } from "../../lib/apiClient";
import type {
  AreaResponse, DrilldownResponse, Grain, KpisResponse, MapResponse, MatrixResponse, MetaResponse,
  PeaksResponse, RankingsResponse, TimelineResponse,
} from "./types";

const get = async <T,>(path: string, params?: URLSearchParams): Promise<T> => {
  const query = params && params.toString() ? `?${params.toString()}` : "";
  const response = await apiClient.get<T>(`/analytics/${path}${query}`, { timeout: 30_000 });
  return response.data;
};

export const getMeta = () => get<MetaResponse>("meta");
export const getMap = (p: URLSearchParams) => get<MapResponse>("map", p);
export const getKpis = (p: URLSearchParams) => get<KpisResponse>("kpis", p);
export const getTimeline = (p: URLSearchParams, grain: Grain) => {
  const q = new URLSearchParams(p);
  q.set("grain", grain);
  return get<TimelineResponse>("timeline", q);
};
export const getRankings = (p: URLSearchParams, limit = 20) => {
  const q = new URLSearchParams(p);
  q.set("limit", String(limit));
  return get<RankingsResponse>("rankings", q);
};
export const getPeaks = (p: URLSearchParams) => get<PeaksResponse>("peaks", p);
export const getMatrix = (p: URLSearchParams) => get<MatrixResponse>("matrix", p);
export const getArea = (code: string, p: URLSearchParams) => get<AreaResponse>(`area/${encodeURIComponent(code)}`, p);
export const getIncidents = (p: URLSearchParams, page: number, pageSize = 25) => {
  const q = new URLSearchParams(p);
  q.set("page", String(page));
  q.set("page_size", String(pageSize));
  return get<DrilldownResponse>("incidents", q);
};

export const downloadExport = async (p: URLSearchParams): Promise<void> => {
  const response = await apiClient.get<Blob>(`/analytics/export.xlsx?${p.toString()}`, {
    responseType: "blob",
    timeout: 60_000,
  });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `analytics_${p.get("date_from")}_${p.get("date_to")}.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

/** Boundary layers are static files served by the app itself; fetched once and cached by the browser. */
export type GeoCollection = {
  type: "FeatureCollection";
  features: Array<{ type: "Feature"; properties: Record<string, string | number | boolean | null>; geometry: unknown }>;
};
let geoPromise: Promise<Record<"mohafaza" | "caza" | "village", GeoCollection>> | null = null;
export const loadGeo = () => {
  if (!geoPromise) {
    const fetchJson = async (name: string): Promise<GeoCollection> => {
      const response = await fetch(`/geo/lb_${name}.geojson`);
      if (!response.ok) throw new Error(`Could not load ${name} boundaries (${response.status})`);
      return (await response.json()) as GeoCollection;
    };
    geoPromise = Promise.all([fetchJson("mohafaza"), fetchJson("caza"), fetchJson("village")])
      .then(([mohafaza, caza, village]) => ({ mohafaza, caza, village }))
      .catch((error) => {
        geoPromise = null;
        throw error;
      });
  }
  return geoPromise;
};
