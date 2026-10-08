export type SummaryStatus =
  | "detected" | "parsed" | "needs_review" | "awaiting_window" | "reconciling"
  | "reconciled" | "skipped_repost" | "failed";

export type SummaryReasonType = "unresolved_location" | "unknown_header" | "casualty_in_summary";

export type SummaryListItem = {
  id: number;
  channel: string | null;
  status: SummaryStatus;
  kind: "full_day" | "partial" | "unknown";
  hidden: boolean;
  window_start: string | null;
  window_end: string | null;
  created_at: string;
  item_count: number;
  unresolved_count: number;
  matched_count: number;
  created_count: number;
  has_open_task: boolean;
  task_id: number | null;
  reasons: Array<{ type: SummaryReasonType; count: number }>;
};

export type SummaryListResponse = { items: SummaryListItem[]; total: number; page: number; page_size: number };

export type SummaryListFilters = {
  status?: string;
  channel?: string;
  dateFrom?: string;
  dateTo?: string;
  hasOpenTask?: boolean;
  includeHidden?: boolean;
  page: number;
  pageSize: number;
};

export type SummaryVillage = { id: number; name_ar: string | null; name_en: string | null; caza_en: string | null };
export type SummaryCondition = { id: number; name_en: string; name_ar: string };

export type SummaryItemDisplayStatus =
  | "pending" | "matched" | "created" | "ambiguous" | "unresolved" | "unknown_header"
  | "header_handled" | "casualty" | "dismissed";

export type SummaryItem = {
  id: number;
  position: number;
  header_text: string | null;
  condition: SummaryCondition | null;
  location_text: string;
  primary_village: SummaryVillage | null;
  secondary_village: SummaryVillage | null;
  modifier: "none" | "outskirts" | "between";
  reported_count: number | null;
  evidence_span: string;
  origin: "parser" | "llm_crosscheck";
  resolution: "resolved" | "unresolved_location" | "unknown_header";
  reconciliation_status: "pending" | "matched" | "created" | "ambiguous";
  display_status: SummaryItemDisplayStatus;
  reason_type: SummaryReasonType | null;
  matched_incident_id: string | null;
  created_incident_id: string | null;
};

export type SummaryReviewReason = {
  type: SummaryReasonType;
  item_ids: number[];
  text?: string;
  origin?: string;
  handled?: { action: string } | null;
};

export type SummaryDetail = SummaryListItem & {
  raw_message_id: number;
  raw_text: string | null;
  window_basis: string | null;
  last_error: string | null;
  process_after: string | null;
  canonical_summary_id: number | null;
  reposts: Array<{ id: number; channel: string | null; created_at: string }>;
  items: SummaryItem[];
  review_task: {
    id: number;
    status: "open" | "resolved" | "dismissed";
    reasons: SummaryReviewReason[];
    resolved_by: string | null;
    resolved_at: string | null;
  } | null;
};

export type ReviewAction = {
  item_id: number;
  action?: "resolve" | "dismiss" | "create_incident";
  village_id?: number;
  save_alias?: boolean;
  condition_ids?: number[];
  save_mapping?: boolean;
};

export type ResolveResponse = {
  handled_item_ids: number[];
  new_item_ids: number[];
  alias_saved_for_items: number[];
  mappings_saved: string[];
  summary: SummaryDetail;
};
