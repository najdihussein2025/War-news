import { useQuery } from "@tanstack/react-query";
import { liveListQueryOptions } from "../../lib/liveListPolling";
import { getAirViolations } from "./api";
import type { AirViolationFilters } from "./types";

export const airViolationKeys = {
  list: (filters: AirViolationFilters) => ["air-violations", filters] as const,
};

export const useAirViolationsQuery = (filters: AirViolationFilters, live = true) =>
  useQuery({
    queryKey: airViolationKeys.list(filters),
    queryFn: () => getAirViolations(filters),
    ...(live ? liveListQueryOptions : {}),
    refetchInterval: live ? 60_000 : false,
    refetchIntervalInBackground: live,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
