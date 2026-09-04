import { apiClient } from "../../lib/apiClient";
import type {
  ConditionOption,
  IncidentDetail,
  IncidentCreatePayload,
  IncidentFilters,
  IncidentDuplicateCandidate,
  IncidentDuplicateDecision,
  IncidentDuplicateResolutionResult,
  IncidentListResponse,
  IncidentUpdatePayload,
  VillageOption,
  RejectedNewsItem,
  RejectedNewsListResponse,
} from "./types";

export const getRejectedNews = async (limit: number, offset: number, search: string): Promise<RejectedNewsListResponse> => {
  const response = await apiClient.get<RejectedNewsListResponse>("/rejected-news", { params: { limit, offset, search: search || undefined } });
  return response.data;
};

export const getRejectedNewsById = async (id: number): Promise<RejectedNewsItem> => {
  const response = await apiClient.get<RejectedNewsItem>(`/rejected-news/${id}`);
  return response.data;
};

export const restoreRejectedNews = async (id: number): Promise<void> => {
  await apiClient.post(`/rejected-news/${id}/restore`);
};

export type WorkbookImportSummary = {
  processed: number;
  succeeded: number;
  skipped: number;
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
  if (filters.cursor) {
    params.set("cursor", filters.cursor);
  }

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
  if (filters.sortOrder) {
    params.set("sort_order", filters.sortOrder);
  }

  const response = await apiClient.get<IncidentListResponse>(
    `/incidents?${params.toString()}`,
  );
  return response.data;
};

export const getConditions = async (): Promise<ConditionOption[]> => {
  const response = await apiClient.get<ConditionOption[]>("/conditions");
  return response.data;
};

export const getVillages = async (): Promise<VillageOption[]> => {
  const response = await apiClient.get<VillageOption[]>("/villages");
  return response.data;
};

export const getIncidentById = async (
  incidentId: string,
): Promise<IncidentDetail> => {
  const response = await apiClient.get<IncidentDetail>(
    `/incidents/${incidentId}`,
  );
  return response.data;
};

export const getIncidentDuplicateCandidate = async (
  incidentId: string,
): Promise<IncidentDuplicateCandidate> => {
  const response = await apiClient.get<IncidentDuplicateCandidate>(
    `/incidents/${incidentId}/duplicate-candidate`,
  );
  return response.data;
};

export const resolveIncidentDuplicate = async (
  incidentId: string,
  matchId: number,
  decision: IncidentDuplicateDecision,
  version: number,
): Promise<IncidentDuplicateResolutionResult> => {
  const response = await apiClient.post<IncidentDuplicateResolutionResult>(
    `/incidents/${incidentId}/duplicate-resolution`,
    { match_id: matchId, decision, version },
  );
  return response.data;
};

export const createIncident = async (payload: IncidentCreatePayload): Promise<IncidentDetail> => {
  const response = await apiClient.post<IncidentDetail>("/incidents", payload);
  return response.data;
};

export const updateIncident = async (incidentId: string, payload: IncidentUpdatePayload): Promise<IncidentDetail> => {
  const response = await apiClient.put<IncidentDetail>(`/incidents/${incidentId}`, payload);
  return response.data;
};

export const updateIncidentDetails = async (
  incidentId: string,
  fields: Record<string, number | string>,
  version: number,
): Promise<IncidentDetail> => {
  const response = await apiClient.patch<IncidentDetail>(
    `/incidents/${incidentId}/details`,
    { fields, version },
  );
  return response.data;
};

export const deleteIncident = async (incidentId: string, version: number): Promise<void> => {
  await apiClient.delete(`/incidents/${incidentId}`, { params: { version } });
};

export const acquireIncidentEditLock = async (incidentId: string): Promise<IncidentDetail> => {
  const response = await apiClient.post<IncidentDetail>(`/incidents/${incidentId}/edit-lock`);
  return response.data;
};

export const releaseIncidentEditLock = async (incidentId: string): Promise<void> => {
  await apiClient.delete(`/incidents/${incidentId}/edit-lock`);
};

export const importIncidents = async (file: File): Promise<WorkbookImportSummary> => {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post<WorkbookImportSummary>("/incidents/import", form);
  return response.data;
};

export const reviewIncident = async (
  incidentId: string,
  status: "verified" | "rejected",
  reason: string | null,
  version: number,
): Promise<IncidentDetail> => {
  const response = await apiClient.post<IncidentDetail>(`/incidents/${incidentId}/verification`, {
    status,
    reason,
    version,
  });
  return response.data;
};
