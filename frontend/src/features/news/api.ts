import { apiClient } from "../../lib/apiClient";
import type {
  ConditionOption,
  IncidentDetail,
  IncidentCreatePayload,
  IncidentFilters,
  IncidentListResponse,
  IncidentUpdatePayload,
  VillageOption,
} from "./types";

export type WorkbookImportSummary = {
  processed: number;
  succeeded: number;
  failed: number;
  row_errors: Array<{
    row: number;
    error: string;
  }>;
};

export const getIncidents = async (
  filters: IncidentFilters,
): Promise<IncidentListResponse> => {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));

  if (filters.village) {
    params.set("village", filters.village);
  }
  if (filters.condition) {
    params.set("condition", filters.condition);
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
  if (filters.verificationStatus) {
    params.set("verification_status", filters.verificationStatus);
  }
  if (filters.duplicateOnly) {
    params.set("duplicate_only", "true");
  }

  const response = await apiClient.get<IncidentListResponse>(
    `/api/incidents?${params.toString()}`,
  );
  return response.data;
};

export const getConditions = async (): Promise<ConditionOption[]> => {
  const response = await apiClient.get<ConditionOption[]>("/api/conditions");
  return response.data;
};

export const getVillages = async (): Promise<VillageOption[]> => {
  const response = await apiClient.get<VillageOption[]>("/api/villages");
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

export const createIncident = async (payload: IncidentCreatePayload): Promise<IncidentDetail> => {
  const response = await apiClient.post<IncidentDetail>("/api/incidents", payload);
  return response.data;
};

export const updateIncident = async (incidentId: string, payload: IncidentUpdatePayload): Promise<IncidentDetail> => {
  const response = await apiClient.put<IncidentDetail>(`/api/incidents/${incidentId}`, payload);
  return response.data;
};

export const updateIncidentDetails = async (
  incidentId: string,
  fields: Record<string, number | string>,
): Promise<IncidentDetail> => {
  const response = await apiClient.patch<IncidentDetail>(
    `/api/incidents/${incidentId}/details`,
    { fields },
  );
  return response.data;
};

export const deleteIncident = async (incidentId: string): Promise<void> => {
  await apiClient.delete(`/api/incidents/${incidentId}`);
};

export const importIncidents = async (file: File): Promise<WorkbookImportSummary> => {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post<WorkbookImportSummary>("/api/incidents/import", form);
  return response.data;
};
