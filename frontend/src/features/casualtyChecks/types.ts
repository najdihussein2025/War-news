export type CasualtyFlagStatus = "open" | "resolved" | "dismissed" | "auto_cleared";
export type CasualtyFlag = {
  id: string; incident_id: string; reason_code: "count_missing" | "aggregate_no_breakdown";
  status: CasualtyFlagStatus; severity: string; summary: string | null;
  evidence_sentence: string | null; affected_types: string[]; village_name: string | null;
  event_date: string | null; source_name: string | null; sibling_count: number; created_at: string;
  group_size: number; incident_ids: string[]; locations: string[];
  resolved_at: string | null; resolved_by: string | null; resolution: ResolutionPayload | null;
  auto_clear_reason: string | null;
};
export type CasualtyFlagPage = { items: CasualtyFlag[]; total: number; page: number; page_size: number };
export type CasualtyFlagFilters = { reason?: string; status: CasualtyFlagStatus; dateFrom?: string; dateTo?: string; q?: string };
export type CasualtyKind = "deaths" | "injuries";
export type CasualtyField = "male_d" | "female_d" | "children_d" | "total_deaths" | "male_i" | "female_i" | "children_i" | "total_injuries";
export type CasualtyIncident = { id: string; village_name: string | null } & Record<CasualtyField, number | null>;
export type ResolutionEntry = { incident_id: string } & Partial<Record<CasualtyField, number>>;
export type ResolutionPayload = { entries?: ResolutionEntry[]; confirmed_unknown?: boolean; note?: string; override?: boolean; override_reason?: string; dismiss_reason?: string };
export type CasualtyFlagDetail = CasualtyFlag & {
  detail: { bulletin_totals?: Partial<Record<CasualtyKind, number | null>>; remaining_total?: Partial<Record<CasualtyKind, number>>; known_exact_counts?: Partial<Record<CasualtyKind, number | null>> };
  message_text: string | null;
  message_snapshot_used: boolean;
  incidents: CasualtyIncident[];
};
export type ResolveCasualtyFlagPayload = { id: string; entries: ResolutionEntry[]; note?: string; override?: boolean; override_reason?: string };
export type ResolveCasualtyFlagResponse = {
  results: Array<{ incident_id: string; resolved: boolean; still_open: boolean; reason: string }>;
  totals: Record<CasualtyKind, { assigned: number; bulletin_total: number | null }>;
  remaining_total: Partial<Record<CasualtyKind, number>>;
};
export type ResolveFieldError = { incident_id: string | null; field: CasualtyField | "entries" | "note" | "override_reason"; code: string; message: string };
export type IncidentCasualtyFlag = { id: string; reason_code: string; severity: string; summary: string | null; created_at: string };
