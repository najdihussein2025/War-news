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
  origin_account: string;
  message_count: number;
  last_seen: string;
  first_seen: string;
  is_blocked: boolean;
};

export type ContentSourceFilters = {
  platform?: string | null;
  search?: string | null;
};

export type ContentSourceRecentMessage = {
  id: number;
  raw_text: string | null;
  message_datetime: string | null;
  received_at: string;
};

export type ContentSourceDetail = ContentSource & {
  recent_messages: ContentSourceRecentMessage[];
};

export type ContentSourceBlock = {
  source_platform: string;
  origin_account: string;
  is_blocked: boolean;
  blocked_at: string | null;
  blocked_by: string | null;
};
