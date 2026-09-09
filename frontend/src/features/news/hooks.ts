import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { liveListQueryOptions } from "../../lib/liveListPolling";
import { getConditions, getIncidentById, getIncidentDuplicateCandidate, getIncidents, getVillages } from "./api";
import type { Incident, IncidentFilters, IncidentListResponse, IncidentStreamEvent } from "./types";

export const incidentKeys = {
  conditions: ["incidents", "conditions"] as const,
  villages: ["incidents", "villages"] as const,
  list: (filters: IncidentFilters) => ["incidents", filters] as const,
  detail: (incidentId: string) => ["incidents", "detail", incidentId] as const,
  duplicateCandidate: (incidentId: string) => ["incidents", "duplicate-candidate", incidentId] as const,
};

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
  });

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

const includesFilterText = (value: string | null, filter?: string) =>
  !filter || Boolean(value?.toLowerCase().includes(filter.toLowerCase()));

const matchesFilters = (incident: IncidentStreamEvent, filters: IncidentFilters) => {
  if (filters.cursor) return false;
  if (!includesFilterText(incident.village, filters.village)) return false;
  if (!includesFilterText(incident.condition, filters.condition)) return false;
  if (filters.sourceType && incident.source?.toLowerCase() !== filters.sourceType.toLowerCase()) return false;
  if (filters.eventDateFrom && incident.event_date < filters.eventDateFrom) return false;
  if (filters.eventDateTo && incident.event_date > filters.eventDateTo) return false;
  if (filters.flaggedOnly && incident.duplicate_flag !== "possible" && incident.verification_status !== "needs_verification") return false;
  if (filters.verificationStatus && incident.verification_status !== filters.verificationStatus) return false;
  if (filters.duplicateOnly && incident.duplicate_flag !== "possible") return false;
  if (
    filters.hasCasualties &&
    !((incident.total_deaths ?? 0) > 0 || (incident.total_injuries ?? 0) > 0)
  ) {
    return false;
  }
  return true;
};

const sortIncidents = (items: Incident[], sortOrder: IncidentFilters["sortOrder"]) =>
  [...items].sort((left, right) => {
    const leftKey = `${left.event_date}T${left.event_time ?? ""}|${left.created_at}|${left.id ?? ""}`;
    const rightKey = `${right.event_date}T${right.event_time ?? ""}|${right.created_at}|${right.id ?? ""}`;
    return sortOrder === "oldest" ? leftKey.localeCompare(rightKey) : rightKey.localeCompare(leftKey);
  });

export const useIncidentStream = (filters: IncidentFilters) => {
  const queryClient = useQueryClient();
  const [isReconnecting, setIsReconnecting] = useState(false);
  const filtersKey = useMemo(() => JSON.stringify(filters), [filters]);

  useEffect(() => {
    const streamUrl = `${API_BASE_URL.replace(/\/$/, "")}/incidents/stream`;
    const source = new EventSource(streamUrl, { withCredentials: true });
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    source.onopen = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      setIsReconnecting(false);
    };

    source.onmessage = (event) => {
      const incident = JSON.parse(event.data) as IncidentStreamEvent;
      const key = incidentKeys.list(filters);
      const shouldPrepend = matchesFilters(incident, filters);
      queryClient.setQueryData<IncidentListResponse>(key, (current) => {
        if (!current) return current;
        if (current.items.some((item) => item.id === incident.id)) {
          return current;
        }
        if (!shouldPrepend) {
          return {
            ...current,
            total: current.total + 1,
            latest_incident_at: incident.created_at,
          };
        }
        const items = sortIncidents([incident, ...current.items], filters.sortOrder).slice(0, current.limit);
        return {
          ...current,
          items,
          total: current.total + 1,
          latest_incident_at: incident.created_at,
          needs_verification_count:
            incident.verification_status === "needs_verification"
              ? current.needs_verification_count + 1
              : current.needs_verification_count,
          casualties_count:
            (incident.total_deaths ?? 0) > 0 || (incident.total_injuries ?? 0) > 0
              ? current.casualties_count + 1
              : current.casualties_count,
        };
      });
    };

    source.onerror = () => {
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => setIsReconnecting(true), 3000);
      }
    };

    return () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      source.close();
    };
  }, [filtersKey, queryClient]);

  return { isReconnecting };
};

export const useIncidentQuery = (incidentId: string | undefined) =>
  useQuery({
    queryKey: incidentKeys.detail(incidentId ?? ""),
    queryFn: () => getIncidentById(incidentId as string),
    enabled: Boolean(incidentId),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

export const useIncidentDuplicateCandidateQuery = (
  incidentId: string | undefined,
  enabled: boolean,
) =>
  useQuery({
    queryKey: incidentKeys.duplicateCandidate(incidentId ?? ""),
    queryFn: () => getIncidentDuplicateCandidate(incidentId as string),
    enabled: Boolean(incidentId) && enabled,
  });
