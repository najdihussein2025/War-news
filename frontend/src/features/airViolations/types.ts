export type AirViolation = {
  id: number;
  raw_message_id: number | null;
  condition_id: number;
  source_id: number;
  village_id?: number | null;
  caza_en: string | null;
  caza_ar: string | null;
  village_en: string | null;
  village_ar: string | null;
  villages?: AirViolationVillage[];
  event_month: string | null;
  war_month: number | null;
  event_date: string;
  event_time: string | null;
  window_id: string | null;
  window_start: string | null;
  window_end: string | null;
  window_violation_count: number | null;
  window_duration_minutes: number | null;
  window_reports: AirViolationWindowReport[];
  /** Villages (helicopter) or cazas (spy balloon) this report counts as; 1 for a window. */
  breach_count?: number | null;
  unit_type?: string | null;
  khabar: string;
  note_1: string | null;
  note_2: string | null;
  source_link: string | null;
  version: number;
  locked_by_user_id: string | null;
  edit_lock_expires_at: string | null;
  created_at: string;
  action_en: string;
  action_ar: string;
  source_name: string;
  is_imported?: boolean;
  import_filename?: string | null;
  import_row?: Record<string, unknown> | null;
  import_enrichment?: { status?: string; reason?: string; text?: string; date_source?: string; published_at?: string; location_basis?: string; location_reference?: string } | null;
};

export type AirViolationWindowReport = {
  id: number;
  event_date: string;
  event_time: string | null;
  khabar: string;
  source_name: string;
  source_link: string | null;
  villages: AirViolationVillage[];
};

export type AirViolationVillage = {
  village_id: number | null;
  name: string;
};

export type AirViolationListResponse = {
  items: AirViolation[];
  total: number;
  limit: number;
  offset: number;
};

export type AirViolationWindow = {
  id: string;
  condition_id?: number | null;
  unit_type?: string | null;
  window_duration_minutes?: number | null;
  caza_en: string;
  caza_ar: string | null;
  window_start: string;
  window_end: string;
  violation_count: number;
  villages: AirViolationVillage[];
};

export type AirViolationWindowListResponse = {
  items: AirViolationWindow[];
  total: number;
  limit: number;
  offset: number;
};

export type AirViolationFilters = {
  limit: number;
  offset: number;
  conditionId?: string;
  importedOnly?: boolean;
  eventDateFrom?: string;
  eventDateTo?: string;
  cazaEn?: string;
  village?: string;
  lastHours?: string;
  sortOrder?: "newest" | "oldest";
};

export type AirViolationSummary = {
  warplanes: number;
  surveillance_aircraft: number;
  helicopters: number;
  spy_balloons: number;
};

export type AirViolationCreateInput = {
  condition_id: number;
  caza_en: string;
  caza_ar?: string | null;
  event_date: string;
  event_time?: string | null;
  khabar: string;
  note_1?: string | null;
  note_2?: string | null;
  source_link?: string | null;
};

export type AirViolationUpdateInput = AirViolationCreateInput & {
  version: number;
};
