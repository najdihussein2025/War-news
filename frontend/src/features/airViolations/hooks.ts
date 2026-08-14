import { useQuery } from "@tanstack/react-query";
import { getAirViolations } from "./api";
import type { AirViolationFilters } from "./types";

export const airViolationKeys = {
  list: (filters: AirViolationFilters) => ["air-violations", filters] as const,
};

export const useAirViolationsQuery = (filters: AirViolationFilters) =>
  useQuery({
    queryKey: airViolationKeys.list(filters),
    queryFn: () => getAirViolations(filters),
  });
