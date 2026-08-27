import { apiClient } from "../../lib/apiClient";
import type { AirViolation, AirViolationCreateInput, AirViolationFilters, AirViolationListResponse, AirViolationSummary, AirViolationUpdateInput } from "./types";
import type { WorkbookImportSummary } from "../news/api";

export const createAirViolation = async (payload: AirViolationCreateInput): Promise<AirViolation> => {
  const response = await apiClient.post<AirViolation>("/api/air-violations", payload);
  return response.data;
};

export const updateAirViolation = async (id: number, payload: AirViolationUpdateInput): Promise<AirViolation> => {
  const response = await apiClient.put<AirViolation>(`/api/air-violations/${id}`, payload);
  return response.data;
};

export const deleteAirViolation = async (id: number, version: number): Promise<void> => {
  await apiClient.delete(`/api/air-violations/${id}`, { params: { version } });
};

export const acquireAirViolationEditLock = async (id: number): Promise<AirViolation> => {
  const response = await apiClient.post<AirViolation>(`/api/air-violations/${id}/edit-lock`);
  return response.data;
};

export const releaseAirViolationEditLock = async (id: number): Promise<void> => {
  await apiClient.delete(`/api/air-violations/${id}/edit-lock`);
};

export const getAirViolations = async (
  filters: AirViolationFilters,
): Promise<AirViolationListResponse> => {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));

  if (filters.conditionId) {
    params.set("condition_id", filters.conditionId);
  }
  if (filters.eventDateFrom) {
    params.set("event_date_from", filters.eventDateFrom);
  }
  if (filters.eventDateTo) {
    params.set("event_date_to", filters.eventDateTo);
  }
  if (filters.cazaEn) {
    params.set("caza_en", filters.cazaEn);
  }
  if (filters.lastHours) {
    params.set("last_hours", filters.lastHours);
  }

  const response = await apiClient.get<AirViolationListResponse>(
    `/api/air-violations?${params.toString()}`,
  );
  return response.data;
};

export const getAirViolationSummary = async (
  filters: AirViolationFilters,
): Promise<AirViolationSummary> => {
  const params = new URLSearchParams();
  if (filters.eventDateFrom) params.set("event_date_from", filters.eventDateFrom);
  if (filters.eventDateTo) params.set("event_date_to", filters.eventDateTo);
  if (filters.cazaEn) params.set("caza_en", filters.cazaEn);
  if (filters.lastHours) params.set("last_hours", filters.lastHours);
  const response = await apiClient.get<AirViolationSummary>(
    `/api/air-violations/summary?${params.toString()}`,
  );
  return response.data;
};

export const importAirViolations = async (file: File): Promise<WorkbookImportSummary> => {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post<WorkbookImportSummary>("/api/air-violations/import", form);
  return response.data;
};

export const exportAirViolations = async (): Promise<void> => {
  const response = await apiClient.get("/api/air-violations/export", { responseType: "blob" });
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "air_violations.xlsx";
  anchor.click();
  URL.revokeObjectURL(url);
};
