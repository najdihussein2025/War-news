import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAuditLogs, getIngestionLog, getIngestionLogs, getLoginLogs, getLogs, getPipelineHealth, retryIngestion } from "./api";
import type { AuditLogFilters, IngestionLogFilters, LoginLogFilters } from "./types";

export const useLogs = () =>
  useQuery({
    queryKey: ["logs"],
    queryFn: getLogs,
  });

export const useAuditLogsQuery = (filters: AuditLogFilters) => useQuery({ queryKey: ["logs", "audit", filters], queryFn: () => getAuditLogs(filters) });

export const useLoginLogsQuery = (filters: LoginLogFilters) =>
  useQuery({
    queryKey: ["logs", "login", filters],
    queryFn: () => getLoginLogs(filters),
  });

export const useIngestionLogsQuery = (filters: IngestionLogFilters) =>
  useQuery({
    queryKey: ["logs", "ingestion", filters],
    queryFn: () => getIngestionLogs(filters),
    refetchInterval: (query) =>
      query.state.data?.items.some((row) => row.status === "running") ? 3000 : 10_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

export const useIngestionLogQuery = (logId: number | null) =>
  useQuery({
    queryKey: ["logs", "ingestion", "detail", logId],
    queryFn: () => getIngestionLog(logId as number),
    enabled: logId !== null,
    refetchInterval: (query) => query.state.data?.status === "running" ? 3000 : false,
  });

export const usePipelineHealthQuery = () =>
  useQuery({
    queryKey: ["logs", "pipeline-health"],
    queryFn: getPipelineHealth,
    // Manual refresh only - no polling / auto-refresh.
    refetchInterval: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });

export const useRetryIngestionMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: retryIngestion,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["logs", "ingestion"] }),
  });
};
