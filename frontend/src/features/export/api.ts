import { apiClient } from "../../lib/apiClient";

export type ExportJob = {
  id: string;
  status: string;
};

export const createExport = async (): Promise<ExportJob> => {
  const response = await apiClient.post<ExportJob>("/export");
  return response.data;
};
