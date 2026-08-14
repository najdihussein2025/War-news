import { apiClient } from "../../lib/apiClient";
import type {
  ContentSourceBlock,
  ContentSourceDetail,
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

const contentSourcePath = (sourcePlatform: string, originAccount: string) =>
  `/api/content-sources/${encodeURIComponent(sourcePlatform)}/${encodeURIComponent(
    originAccount,
  )}`;

export const getContentSource = async (
  sourcePlatform: string,
  originAccount: string,
): Promise<ContentSourceDetail> => {
  const response = await apiClient.get<ContentSourceDetail>(
    contentSourcePath(sourcePlatform, originAccount),
  );
  return response.data;
};

export const setContentSourceBlocked = async (
  sourcePlatform: string,
  originAccount: string,
  isBlocked: boolean,
): Promise<ContentSourceBlock> => {
  const response = await apiClient.patch<ContentSourceBlock>(
    `${contentSourcePath(sourcePlatform, originAccount)}/block`,
    { is_blocked: isBlocked },
  );
  return response.data;
};
