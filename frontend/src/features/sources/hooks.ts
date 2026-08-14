import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getContentSource,
  getContentSources,
  getSource,
  getSources,
  setContentSourceBlocked,
  setSourceActive,
} from "./api";
import type {
  ContentSource,
  ContentSourceDetail,
  ContentSourceFilters,
  Source,
} from "./types";

const sourceKeys = {
  list: ["sources"] as const,
  detail: (sourceId: number) => ["sources", "detail", sourceId] as const,
  contentSources: (filters: ContentSourceFilters) => [
    "sources",
    "content-sources",
    filters.platform || null,
    filters.search?.trim() || null,
  ] as const,
  contentSourceDetail: (sourcePlatform: string, originAccount: string) =>
    ["sources", "content-sources", "detail", sourcePlatform, originAccount] as const,
};

export const useSourcesQuery = () =>
  useQuery({
    queryKey: sourceKeys.list,
    queryFn: getSources,
  });

export const useSourceDetailQuery = (sourceId: number | null) =>
  useQuery({
    queryKey: sourceKeys.detail(sourceId ?? 0),
    queryFn: () => getSource(sourceId as number),
    enabled: sourceId !== null,
  });

export const useContentSourcesQuery = (filters: ContentSourceFilters = {}) =>
  useQuery({
    queryKey: sourceKeys.contentSources(filters),
    queryFn: () =>
      getContentSources({
        platform: filters.platform || null,
        search: filters.search?.trim() || null,
      }),
  });

export const useContentSourceDetailQuery = (
  sourcePlatform: string | null,
  originAccount: string | null,
) =>
  useQuery({
    queryKey: sourceKeys.contentSourceDetail(
      sourcePlatform ?? "",
      originAccount ?? "",
    ),
    queryFn: () => getContentSource(sourcePlatform as string, originAccount as string),
    enabled: sourcePlatform !== null && originAccount !== null,
  });

type ContentSourceBlockVariables = {
  sourcePlatform: string;
  originAccount: string;
  isBlocked: boolean;
};

const contentSourceMatches = (
  contentSource: ContentSource,
  variables: ContentSourceBlockVariables,
) =>
  contentSource.source_platform === variables.sourcePlatform &&
  contentSource.origin_account === variables.originAccount;

export const useSetContentSourceBlockedMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sourcePlatform,
      originAccount,
      isBlocked,
    }: ContentSourceBlockVariables) =>
      setContentSourceBlocked(sourcePlatform, originAccount, isBlocked),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ["sources", "content-sources"] });

      const listSnapshots = queryClient.getQueriesData<ContentSource[]>({
        predicate: (query) =>
          query.queryKey[0] === "sources" &&
          query.queryKey[1] === "content-sources" &&
          query.queryKey[2] !== "detail",
      });
      const detailSnapshots = queryClient.getQueriesData<ContentSourceDetail>({
        queryKey: ["sources", "content-sources", "detail"],
      });

      listSnapshots.forEach(([queryKey, current]) => {
        queryClient.setQueryData<ContentSource[]>(queryKey, (rows = current ?? []) =>
          rows.map((contentSource) =>
            contentSourceMatches(contentSource, variables)
              ? { ...contentSource, is_blocked: variables.isBlocked }
              : contentSource,
          ),
        );
      });

      detailSnapshots.forEach(([queryKey, current]) => {
        if (!current || !contentSourceMatches(current, variables)) {
          return;
        }
        queryClient.setQueryData<ContentSourceDetail>(queryKey, {
          ...current,
          is_blocked: variables.isBlocked,
        });
      });

      return { listSnapshots, detailSnapshots };
    },
    onError: (_error, _variables, context) => {
      context?.listSnapshots.forEach(([queryKey, data]) => {
        queryClient.setQueryData(queryKey, data);
      });
      context?.detailSnapshots.forEach(([queryKey, data]) => {
        queryClient.setQueryData(queryKey, data);
      });
    },
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: ["sources", "content-sources"] });
      queryClient.invalidateQueries({
        queryKey: sourceKeys.contentSourceDetail(
          variables.sourcePlatform,
          variables.originAccount,
        ),
      });
    },
  });
};

type SourceActiveVariables = {
  sourceId: number;
  isActive: boolean;
};

export const useSetSourceActiveMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ sourceId, isActive }: SourceActiveVariables) =>
      setSourceActive(sourceId, isActive),
    onMutate: async ({ sourceId, isActive }) => {
      await queryClient.cancelQueries({ queryKey: sourceKeys.list });
      const previousSources = queryClient.getQueryData<Source[]>(sourceKeys.list);

      queryClient.setQueryData<Source[]>(sourceKeys.list, (current = []) =>
        current.map((source) =>
          source.id === sourceId ? { ...source, is_active: isActive } : source,
        ),
      );

      return { previousSources };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousSources) {
        queryClient.setQueryData(sourceKeys.list, context.previousSources);
      }
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: sourceKeys.list }),
  });
};
