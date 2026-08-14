import { useQuery } from "@tanstack/react-query";
import { getAccounts } from "./api";

export const useAccounts = () =>
  useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchInterval: 30_000,
  });
