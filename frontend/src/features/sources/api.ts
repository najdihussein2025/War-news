import { apiClient } from "../../lib/apiClient";
import type {
  ContentSource,
  ContentSourceFilters,
  Source,
  SourceDetail,
} from "./types";

export const getSources = async (): Promise<Source[]> => {
  const response = await apiClient.get<Source[]>("/api/sources");
  return response.data;
};

export const getSource = async (sourceId: number): Promise<SourceDetail> => {
  const response = await apiClient.get<SourceDetail>(`/api/sources/${sourceId}`);
  return response.data;
};

export const setSourceActive = async (
  sourceId: number,
  isActive: boolean,
): Promise<SourceDetail> => {
  const action = isActive ? "resume" : "pause";
  const response = await apiClient.post<SourceDetail>(
    `/api/sources/${sourceId}/${action}`,
  );
  return response.data;
};

export const getContentSources = async (
  filters: ContentSourceFilters = {},
): Promise<ContentSource[]> => {
  const response = await apiClient.get<ContentSource[]>("/api/content-sources", {
    params: {
      platform: filters.platform || undefined,
      search: filters.search || undefined,
    },
  });
  return response.data;
};
