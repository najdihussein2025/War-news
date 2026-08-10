import { useQuery } from "@tanstack/react-query";
import { getSources } from "./api";

export const useSources = () =>
  useQuery({
    queryKey: ["sources"],
    queryFn: getSources,
  });
