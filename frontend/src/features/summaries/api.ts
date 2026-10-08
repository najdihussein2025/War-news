import { apiClient } from "../../lib/apiClient";
import type { ResolveResponse, ReviewAction, SummaryDetail, SummaryListFilters, SummaryListResponse } from "./types";

export const getSummaries = async (filters: SummaryListFilters) =>
  (
    await apiClient.get<SummaryListResponse>("/summaries", {
      params: {
        status: filters.status || undefined,
        channel: filters.channel || undefined,
        date_from: filters.dateFrom || undefined,
        date_to: filters.dateTo || undefined,
        has_open_task: filters.hasOpenTask,
        include_hidden: filters.includeHidden ? true : undefined,
        page: filters.page,
        page_size: filters.pageSize,
      },
    })
  ).data;

export const getSummary = async (id: number) => (await apiClient.get<SummaryDetail>(`/summaries/${id}`)).data;

export const resolveSummaryTask = async ({ id, actions }: { id: number; actions: ReviewAction[] }) =>
  (await apiClient.post<ResolveResponse>(`/summaries/${id}/review-task/resolve`, { actions })).data;

export const dismissSummaryTask = async (id: number) =>
  (await apiClient.post<{ summary: SummaryDetail }>(`/summaries/${id}/review-task/dismiss`)).data;
