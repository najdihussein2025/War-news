import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { dismissSummaryTask, getSummaries, getSummary, resolveSummaryTask } from "./api";
import type { SummaryListFilters } from "./types";

export const summaryKeys = {
  all: ["summaries"] as const,
  list: (filters: SummaryListFilters) => ["summaries", "list", filters] as const,
  detail: (id: number) => ["summaries", "detail", id] as const,
};

export const useSummariesQuery = (filters: SummaryListFilters) =>
  useQuery({ queryKey: summaryKeys.list(filters), queryFn: () => getSummaries(filters), refetchInterval: 60_000 });

export const useSummaryQuery = (id?: number) =>
  useQuery({
    queryKey: summaryKeys.detail(id ?? 0),
    queryFn: () => getSummary(id as number),
    enabled: id !== undefined && Number.isFinite(id),
  });

const useSummaryMutation = <T, R>(mutationFn: (value: T) => Promise<R>) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: summaryKeys.all });
      await client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
};

export const useResolveSummaryTask = () => useSummaryMutation(resolveSummaryTask);
export const useDismissSummaryTask = () => useSummaryMutation(dismissSummaryTask);
