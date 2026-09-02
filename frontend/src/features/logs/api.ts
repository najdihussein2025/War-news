import { apiClient } from "../../lib/apiClient";
import type { AuditLogFilters, AuditLogPage, IngestionLog, IngestionLogFilters, IngestionLogPage, LoginLogFilters, LoginLogPage, PipelineHealth } from "./types";

export type ModerationLog = {
  id: string;
  action: string;
  created_at: string;
};

export const getLogs = async (): Promise<ModerationLog[]> => {
  const response = await apiClient.get<ModerationLog[]>("/logs");
  return response.data;
};

export const getAuditLogs = async (filters: AuditLogFilters): Promise<AuditLogPage> => {
  const response = await apiClient.get<AuditLogPage>("/logs/audit", { params: { search: filters.search?.trim() || undefined, action: filters.action || undefined, date_from: filters.dateFrom || undefined, date_to: filters.dateTo || undefined, page: filters.page ?? 1, page_size: filters.pageSize ?? 100 } });
  return response.data;
};

export const getLoginLogs = async (
  filters: LoginLogFilters,
): Promise<LoginLogPage> => {
  const response = await apiClient.get<LoginLogPage>("/logs/login", {
    params: {
      search: filters.search?.trim() || undefined,
      result: filters.result ?? "success",
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      page: filters.page ?? 1,
      page_size: filters.pageSize ?? 25,
    },
  });
  return response.data;
};

export const getIngestionLogs = async (filters: IngestionLogFilters): Promise<IngestionLogPage> => {
  const response = await apiClient.get<IngestionLogPage>("/logs/ingestion", {
    params: {
      source_id: filters.sourceId || undefined,
      status: filters.status === "all" ? undefined : filters.status,
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      page: filters.page ?? 1,
      page_size: filters.pageSize ?? 100,
    },
  });
  return response.data;
};

export const getIngestionLog = async (logId: number): Promise<IngestionLog> => {
  const response = await apiClient.get<IngestionLog>(`/logs/ingestion/${logId}`);
  return response.data;
};

export const retryIngestion = async (logId: number): Promise<IngestionLog> => {
  const response = await apiClient.post<IngestionLog>(`/logs/ingestion/${logId}/retry`);
  return response.data;
};

export const getPipelineHealth = async (): Promise<PipelineHealth> => {
  const response = await apiClient.get<PipelineHealth>("/pipeline/health");
  return response.data;
};
