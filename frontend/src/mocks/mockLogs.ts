export type MockAuditLog = {
  id: string;
  action: string;
  performed_by: string;
  target: string;
  timestamp: string;
  old_values: Record<string, string>;
  new_values: Record<string, string>;
};

export type MockIngestionLog = {
  id: string;
  source_name: string;
  run_timestamp: string;
  messages_fetched: number;
  parsed: number;
  flagged: number;
  failed: number;
  status: "completed" | "failed" | "running";
};

export const mockAuditLogs: MockAuditLog[] = [
  {
    id: "aud_001",
    action: "incident.auto_published",
    performed_by: "Maya Haddad",
    target: "inc_008",
    timestamp: "2026-08-10T10:20:00+03:00",
    old_values: { parser_state: "matched" },
    new_values: { status: "approved", duplicate_flag: "none" },
  },
  {
    id: "aud_002",
    action: "source.paused",
    performed_by: "Leila Mansour",
    target: "CNRS Local Classification",
    timestamp: "2026-08-09T22:30:00+03:00",
    old_values: { is_active: "true", health: "error" },
    new_values: { is_active: "false", health: "paused" },
  },
  {
    id: "aud_003",
    action: "user.updated",
    performed_by: "Super Admin",
    target: "omar.fares",
    timestamp: "2026-08-08T12:00:00+03:00",
    old_values: { is_active: "true" },
    new_values: { is_active: "false" },
  },
];

export const mockIngestionLogs: MockIngestionLog[] = [
  { id: "ing_001", source_name: "South Lebanon Field Reports", run_timestamp: "2026-08-10T10:45:00+03:00", messages_fetched: 84, parsed: 72, flagged: 9, failed: 3, status: "completed" },
  { id: "ing_002", source_name: "CNRS Standard Feed", run_timestamp: "2026-08-10T09:30:00+03:00", messages_fetched: 37, parsed: 34, flagged: 4, failed: 0, status: "completed" },
  { id: "ing_003", source_name: "CNRS Local Classification", run_timestamp: "2026-08-09T22:15:00+03:00", messages_fetched: 12, parsed: 5, flagged: 0, failed: 7, status: "failed" },
];
