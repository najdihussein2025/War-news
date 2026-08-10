import { useQuery } from "@tanstack/react-query";
import { getLogs } from "./api";

export const useLogs = () =>
  useQuery({
    queryKey: ["logs"],
    queryFn: getLogs,
  });
