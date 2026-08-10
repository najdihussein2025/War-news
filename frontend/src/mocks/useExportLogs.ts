import { mockExportLogs } from "./mockExportLogs";

export const useExportLogs = () => ({
  data: mockExportLogs,
  isLoading: false,
  isError: false,
});
