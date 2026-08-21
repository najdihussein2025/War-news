import { useQuery } from "@tanstack/react-query";
import { liveListQueryOptions } from "../../lib/liveListPolling";
import { getIncidentById, getIncidents } from "./api";
import type { IncidentFilters } from "./types";

export const incidentKeys = {
  list: (filters: IncidentFilters) => ["incidents", filters] as const,
  detail: (incidentId: string) => ["incidents", "detail", incidentId] as const,
};

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
