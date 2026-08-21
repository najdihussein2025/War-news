import { useQuery } from "@tanstack/react-query";
import { liveListQueryOptions } from "../../lib/liveListPolling";
import { getConditions, getIncidentById, getIncidents, getVillages } from "./api";
import type { IncidentFilters } from "./types";

export const incidentKeys = {
  conditions: ["incidents", "conditions"] as const,
  villages: ["incidents", "villages"] as const,
  list: (filters: IncidentFilters) => ["incidents", filters] as const,
  detail: (incidentId: string) => ["incidents", "detail", incidentId] as const,
};

export const useIncidentsQuery = (filters: IncidentFilters, live = true) =>
export const useConditionsQuery = () =>
  useQuery({
    queryKey: incidentKeys.conditions,
    queryFn: getConditions,
    staleTime: 5 * 60 * 1000,
  });

export const useVillagesQuery = () =>
  useQuery({
    queryKey: incidentKeys.villages,
    queryFn: getVillages,
    staleTime: 5 * 60 * 1000,
  });

export const useIncidentsQuery = (filters: IncidentFilters, live = true) =>
  useQuery({
    queryKey: incidentKeys.list(filters),
    queryFn: () => getIncidents(filters),
    ...(live ? liveListQueryOptions : {}),
    refetchOnWindowFocus: !live,
  });

export const useIncidentQuery = (incidentId: string | undefined) =>
  useQuery({
    queryKey: incidentKeys.detail(incidentId ?? ""),
    queryFn: () => getIncidentById(incidentId as string),
    enabled: Boolean(incidentId),
  });
