import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  getArea, getIncidents, getKpis, getMap, getMatrix, getMeta, getPeaks, getRankings, getTab, getTimeline, loadGeo,
} from "./api";
import type { AnalyticsTabId, Grain, MapTab, OverviewTab } from "./types";

const STALE = 60_000;

export const useDebounced = <T,>(value: T, delay = 250): T => {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
};

export const useMeta = () =>
  useQuery({ queryKey: ["analytics", "meta"], queryFn: getMeta, staleTime: STALE, refetchInterval: 120_000 });

export const useGeo = () => useQuery({ queryKey: ["analytics", "geo"], queryFn: loadGeo, staleTime: Infinity, gcTime: Infinity });

export const useMapData = (params: URLSearchParams, enabled = true) =>
  useQuery({
    queryKey: ["analytics", "map", params.toString()],
    queryFn: () => getMap(params),
    staleTime: STALE,
    placeholderData: keepPreviousData,
    enabled,
    retry: (count, error) => ((error as { response?: { status?: number } }).response?.status === 422 ? false : count < 2),
  });

export const usePrefetchMap = () => {
  const client = useQueryClient();
  return (params: URLSearchParams) =>
    client.fetchQuery({ queryKey: ["analytics", "map", params.toString()], queryFn: () => getMap(params), staleTime: STALE });
};

export const useKpis = (params: URLSearchParams, enabled = true) =>
  useQuery({ queryKey: ["analytics", "kpis", params.toString()], queryFn: () => getKpis(params), staleTime: STALE, placeholderData: keepPreviousData, enabled });

export const useTimeline = (params: URLSearchParams, grain: Grain, enabled = true) =>
  useQuery({ queryKey: ["analytics", "timeline", params.toString(), grain], queryFn: () => getTimeline(params, grain), staleTime: STALE, placeholderData: keepPreviousData, enabled });

export const usePeaks = (params: URLSearchParams, enabled = true) =>
  useQuery({ queryKey: ["analytics", "peaks", params.toString()], queryFn: () => getPeaks(params), staleTime: STALE, placeholderData: keepPreviousData, enabled });

export const useRankings = (params: URLSearchParams, limit: number, enabled = true) =>
  useQuery({ queryKey: ["analytics", "rankings", params.toString(), limit], queryFn: () => getRankings(params, limit), staleTime: STALE, placeholderData: keepPreviousData, enabled });

export const useMatrix = (params: URLSearchParams, enabled = true) =>
  useQuery({ queryKey: ["analytics", "matrix", params.toString()], queryFn: () => getMatrix(params), staleTime: STALE, placeholderData: keepPreviousData, enabled });

export const useArea = (code: string | null, params: URLSearchParams) =>
  useQuery({ queryKey: ["analytics", "area", code, params.toString()], queryFn: () => getArea(code as string, params), staleTime: STALE, enabled: Boolean(code) });

/** One query per tab, keyed on the filters and grain; only the active tab passes ``enabled``. */
const useTab = <T,>(tab: AnalyticsTabId, params: URLSearchParams, grain: Grain, enabled: boolean) =>
  useQuery({
    queryKey: ["analytics", "tab", tab, params.toString(), grain],
    queryFn: () => getTab<T>(tab, params, grain),
    staleTime: STALE,
    placeholderData: keepPreviousData,
    enabled,
    retry: (count, error) => ((error as { response?: { status?: number } }).response?.status === 422 ? false : count < 2),
  });

export const useAnalyticsOverview = (params: URLSearchParams, grain: Grain, enabled: boolean) =>
  useTab<OverviewTab>("overview", params, grain, enabled);
export const useAnalyticsMap = (params: URLSearchParams, grain: Grain, enabled: boolean) =>
  useTab<MapTab>("map", params, grain, enabled);

export const useIncidents =(params: URLSearchParams, page: number, enabled: boolean) =>
  useQuery({ queryKey: ["analytics", "incidents", params.toString(), page], queryFn: () => getIncidents(params, page), staleTime: STALE, placeholderData: keepPreviousData, enabled });
