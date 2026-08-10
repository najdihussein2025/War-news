import { mockAuditLogs, mockIngestionLogs, mockLoginLogs } from "./mockLogs";

export const useAuditLogs = () => ({
  data: mockAuditLogs,
  isLoading: false,
  isError: false,
});

export const useLoginLogs = () => ({
  data: mockLoginLogs,
  isLoading: false,
  isError: false,
});

export const useIngestionLogs = () => ({
  data: mockIngestionLogs,
  isLoading: false,
  isError: false,
});
