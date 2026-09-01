export type LoginLogResultFilter = "success" | "failure" | "all";

export type AuditLog = { id: string; action: string; performed_by: string; actor_id: string | null; target_type: string; target: string; ip: string | null; old_values: Record<string, unknown> | null; new_values: Record<string, unknown> | null; timestamp: string };
export type AuditLogFilters = { search?: string; action?: string; dateFrom?: string; dateTo?: string; page?: number; pageSize?: number };
export type AuditLogPage = { items: AuditLog[]; total: number; page: number; page_size: number };

export type LoginLog = {
  id: string;
  username: string;
  timestamp: string;
  success: boolean;
  ip: string;
};

export type LoginLogFilters = {
  search?: string;
  result?: LoginLogResultFilter;
  dateFrom?: string;
  dateTo?: string;
  createdAfter?: string;
  page?: number;
  pageSize?: number;
};

export type LoginLogPage = {
  items: LoginLog[];
  total: number;
  page: number;
  page_size: number;
};

export type IngestionStatus = "running" | "completed" | "failed" | "interrupted";

export type IngestionLog = {
  id: number;
  source_id: number;
  source_name: string;
  source_platforms: string[];
  platform_breakdown: Record<string, {
    fetched: number;
    parsed: number;
    flagged: number;
    failed: number;
    blocked: number;
  }>;
  run_timestamp: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  messages_fetched: number;
  messages_parsed: number;
  messages_flagged: number;
  messages_failed: number;
  messages_blocked: number;
  status: IngestionStatus;
  error_message: string | null;
  retry_of_id: number | null;
};

export type IngestionLogFilters = {
  sourceId?: number;
  status?: IngestionStatus | "all";
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
};

export type IngestionLogPage = {
  items: IngestionLog[];
  total: number;
  page: number;
  page_size: number;
};
