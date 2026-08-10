export type SourceType = "Telegram" | "CNRS API" | "CNRS Local LLM";
export type SourceHealth = "healthy" | "error" | "paused";

export type MockSource = {
  id: string;
  type: SourceType;
  name: string;
  last_cursor: string;
  last_run_at: string | null;
  is_active: boolean;
  health: SourceHealth;
  error_reason?: string;
  messages_fetched_last_run: number;
};

export const mockSources: MockSource[] = [
  {
    id: "src_001",
    type: "Telegram",
    name: "South Lebanon Field Reports",
    last_cursor: "tg:842199",
    last_run_at: "2026-08-10T10:45:00+03:00",
    is_active: true,
    health: "healthy",
    messages_fetched_last_run: 84,
  },
  {
    id: "src_002",
    type: "CNRS API",
    name: "CNRS Standard Feed",
    last_cursor: "cnrs:2026-08-10:09",
    last_run_at: "2026-08-10T09:30:00+03:00",
    is_active: true,
    health: "healthy",
    messages_fetched_last_run: 37,
  },
  {
    id: "src_003",
    type: "CNRS Local LLM",
    name: "CNRS Local Classification",
    last_cursor: "llm:batch-118",
    last_run_at: "2026-08-09T22:15:00+03:00",
    is_active: true,
    health: "error",
    error_reason: "Auth token expired",
    messages_fetched_last_run: 12,
  },
  {
    id: "src_004",
    type: "Telegram",
    name: "Municipality Manual Watch",
    last_cursor: "tg:paused-442",
    last_run_at: "2026-07-31T16:20:00+03:00",
    is_active: false,
    health: "paused",
    messages_fetched_last_run: 0,
  },
];
