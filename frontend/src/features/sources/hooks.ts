import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getContentSources, getSource, getSources, setSourceActive } from "./api";
import type { ContentSourceFilters, Source } from "./types";

const sourceKeys = {
  list: ["sources"] as const,
  detail: (sourceId: number) => ["sources", "detail", sourceId] as const,
  contentSources: (filters: ContentSourceFilters) => [
    "sources",
    "content-sources",
    filters.platform || null,
    filters.search?.trim() || null,
  ] as const,
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
