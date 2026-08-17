import { apiClient } from "../../lib/apiClient";
import type {
  IncidentDetail,
  IncidentFilters,
  IncidentListResponse,
} from "./types";

export const getIncidents = async (
  filters: IncidentFilters,
): Promise<IncidentListResponse> => {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));

  if (filters.village) {
    params.set("village", filters.village);
  }
  if (filters.sourceType) {
    params.set("source_type", filters.sourceType);
  }
  if (filters.eventDateFrom) {
    params.set("event_date_from", filters.eventDateFrom);
  }
  if (filters.eventDateTo) {
    params.set("event_date_to", filters.eventDateTo);
  }
  if (filters.flaggedOnly) {
    params.set("flagged_only", "true");
  }

  const response = await apiClient.get<IncidentListResponse>(
    `/api/incidents?${params.toString()}`,
  );
  return response.data;
};

export const getIncidentById = async (
  incidentId: string,
): Promise<IncidentDetail> => {
  const response = await apiClient.get<IncidentDetail>(
    `/api/incidents/${incidentId}`,
  );
  return response.data;
};
