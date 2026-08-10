import { useQuery } from "@tanstack/react-query";
import { getAccounts } from "./api";

export const useAccounts = () =>
  useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
  });
