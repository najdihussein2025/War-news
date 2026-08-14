export type Source = {
  id: number;
  type: "telegram" | "twitter" | "facebook" | "website" | "api" | "manual" | "other";
  name: string;
  is_active: boolean;
  last_message_at: string | null;
  total_messages: number;
};

export type SourceDetail = Source & {
  external_id: string | null;
  created_at: string;
  last_cursor: string | null;
};

export type ContentSource = {
  source_platform: string;
  source_name: string;
  message_count: number;
  last_seen: string;
};

export type ContentSourceFilters = {
  platform?: string | null;
  search?: string | null;
};
