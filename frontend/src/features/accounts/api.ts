import { apiClient } from "../../lib/apiClient";
import type { Account } from "./types";

export const getAccounts = async (): Promise<Account[]> => {
  const response = await apiClient.get<Account[]>("/accounts");
  return response.data;
};
