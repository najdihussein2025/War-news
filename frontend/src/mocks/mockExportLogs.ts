export type ExportStatus = "running" | "completed" | "failed";

export type MockExportLog = {
  id: string;
  requested_by: string;
  timestamp: string;
  status: ExportStatus;
  row_count: number | null;
  file_name: string;
};

export const mockExportLogs: MockExportLog[] = [
  {
    id: "exp_001",
    requested_by: "Maya Haddad",
    timestamp: "2026-08-10T09:30:00+03:00",
    status: "completed",
    row_count: 1842,
    file_name: "war-news-2026-08-10.csv",
  },
  {
    id: "exp_002",
    requested_by: "Leila Mansour",
    timestamp: "2026-08-09T17:10:00+03:00",
    status: "failed",
    row_count: null,
    file_name: "war-news-2026-08-09.csv",
  },
  {
    id: "exp_003",
    requested_by: "Karim Nasser",
    timestamp: "2026-08-04T12:45:00+03:00",
    status: "completed",
    row_count: 927,
    file_name: "reviewed-incidents-august.csv",
  },
];
