import { apiClient } from "../../lib/apiClient";

export type ModerationLog = {
  id: string;
  action: string;
  created_at: string;
};

export const getLogs = async (): Promise<ModerationLog[]> => {
  const response = await apiClient.get<ModerationLog[]>("/logs");
  return response.data;
};
