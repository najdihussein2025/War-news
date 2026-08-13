import { useQuery } from "@tanstack/react-query";
import { getSources } from "./api";

export const useSourcesQuery = () =>
  useQuery({
    queryKey: ["sources"],
    queryFn: getSources,
  });
