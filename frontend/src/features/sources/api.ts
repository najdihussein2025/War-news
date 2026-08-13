import { apiClient } from "../../lib/apiClient";
import type { Source } from "./types";

export const getSources = async (): Promise<Source[]> => {
  const response = await apiClient.get<Source[]>("/api/sources");
  return response.data;
};
