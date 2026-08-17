import { apiClient } from "../../lib/apiClient";
import type { AirViolationFilters, AirViolationListResponse } from "./types";

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

  const response = await apiClient.get<AirViolationListResponse>(
    `/api/air-violations?${params.toString()}`,
  );
  return response.data;
};

export const importAirViolations = async (file: File): Promise<{ imported: number; skipped: number; failed: number }> => {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post("/api/air-violations/import", form);
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
