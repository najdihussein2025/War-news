export type IncidentSource =
  | "Telegram"
  | "API"
  | "Manual"
  | "Twitter"
  | "Facebook"
  | "Website"
  | "Other";

export type Incident = {
  id: string | null;
  raw_message_id: number | null;
  raw_status: string | null;
  village: string | null;
  condition: string | null;
  condition_ar: string | null;
  event_date: string;
  event_time: string | null;
  khabar: string;
  source: IncidentSource | null;
  source_reference: string | null;
  source_name: string | null;
  total_deaths?: number | null;
  total_injuries?: number | null;
  matched: boolean;
  verification_status: "auto_processed" | "needs_verification" | "verified" | "rejected";
  verification_reason: string | null;
  verified_by_user_id: string | null;
  verified_at: string | null;
  duplicate_flag: "none" | "possible";
  duplicate_level?: "low" | "medium" | "high" | null;
  duplicate_similarity_score?: number | null;
  details_pending: boolean;
  created_at: string;
  version: number;
  locked_by_user_id: string | null;
  edit_lock_expires_at: string | null;
};

export type IncidentListResponse = {
  items: Incident[];
  total: number;
  limit: number;
  next_cursor: string | null;
  latest_incident_at: string | null;
  needs_verification_count: number;
  casualties_count: number;
};

export type IncidentStreamEvent = Incident & {
  village_id: number | null;
  condition_id: number | null;
};

export type IncidentFilters = {
  limit: number;
  cursor?: string;
  village?: string;
  condition?: string;
  sourceType?: string;
  sourceName?: string;
  eventDateFrom?: string;
  eventDateTo?: string;
  flaggedOnly?: boolean;
  verificationStatus?: "auto_processed" | "needs_verification" | "verified" | "rejected";
  duplicateOnly?: boolean;
  hasCasualties?: boolean;
  sortOrder?: "newest" | "oldest";
};

export type ConditionOption = {
  id: number;
  action_en: string;
  action_ar: string;
};

export type VillageOption = {
  id: number;
  value: string;
  label: string;
  ref_name_en: string | null;
  ref_name_ar: string | null;
  caza_en: string | null;
  caza_ar: string | null;
};

export type CasualtyDemographics = {
  male_d: number | null;
  male_i: number | null;
  female_d: number | null;
  female_i: number | null;
  children_d: number | null;
  children_i: number | null;
};

export type IncidentVillageDetails = {
  id: number;
  acs_code: number;
  acs_name: string | null;
  cad_name: string | null;
  ref_name_en: string | null;
  ref_name_ar: string | null;
  caza_en: string | null;
  caza_ar: string | null;
  mohafaza_en: string | null;
  mohafaza_ar: string | null;
  coord_x: number | null;
  coord_y: number | null;
};

export type IncidentCategorySection = Record<string, number | string>;

export type BulletinCasualtyGroup = {
  casualty_scope: "per_village_exact" | "bulletin_aggregate" | "unspecified";
  total_deaths: number | null;
  total_injuries: number | null;
  breakdown_status: "pending" | "resolved" | "expired" | "n_a";
  window_expires_at: string | null;
  resolved_at: string | null;
  resolved_by_raw_message_id: number | null;
};

export type IncidentDetail = Incident & {
  village_details: IncidentVillageDetails | null;
  note: string | null;
  moh: string | null;
  martyrs: string | null;
  worker_name: string | null;
  source_link: string | null;
  source_link_2: string | null;
  total_deaths: number | null;
  total_injuries: number | null;
  deaths: number | null;
  injuries: number | null;
  village_review_required?: boolean;
  any_village_low_confidence?: boolean;
  resolved_by_geo_context?: boolean;
  geo_context_anchor_village_id?: number | null;
  geo_context_anchor_village_name?: string | null;
  alternate_candidate_village_id?: number | null;
  alternate_candidate_village_name?: string | null;
  casualty_demographics: CasualtyDemographics;
  bulletin_group?: BulletinCasualtyGroup | null;
  lebanese_army: IncidentCategorySection | null;
  unifil: IncidentCategorySection | null;
  municipality: IncidentCategorySection | null;
  school_university: IncidentCategorySection | null;
  religious_cultural: IncidentCategorySection | null;
  hospital: IncidentCategorySection | null;
  health_center: IncidentCategorySection | null;
  emergency_civil_defense: IncidentCategorySection | null;
  press: IncidentCategorySection | null;
  government_building: IncidentCategorySection | null;
  road_bridge: IncidentCategorySection | null;
  vehicles: IncidentCategorySection | null;
  crossings_other: IncidentCategorySection | null;
  warning_classification: IncidentCategorySection | null;
};

export type IncidentUpdatePayload = {
  version: number;
  event_date: string;
  event_time: string | null;
  khabar: string;
  note: string | null;
  worker_name: string | null;
  source_link: string | null;
  source_link_2: string | null;
  total_deaths: number | null;
  total_injuries: number | null;
  deaths: number | null;
  injuries: number | null;
};

export type IncidentCreatePayload = {
  village: string;
  condition: string;
  event_date: string;
  event_time: string | null;
  khabar: string;
  note: string | null;
  source_link: string | null;
};

export type RejectedNewsItem = {
  id: number;
  khabar: string;
  summary: string;
  message_datetime: string | null;
  received_at: string;
  source_name: string | null;
  source_platform: string | null;
  external_message_id: string | null;
  rejection_type: "not_relevant" | "uncertain" | "duplicate" | "rejected";
  rejection_reason: string;
  rejection_reason_en: string;
  rejection_reason_ar: string;
  duplicate_of_id: number | null;
};

export type RejectedNewsListResponse = {
  items: RejectedNewsItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DuplicateCandidateIncident = {
  id: string;
  village: string | null;
  condition: string | null;
  event_date: string;
  event_time: string | null;
  khabar: string;
  source: IncidentSource | null;
  source_reference: string | null;
  source_name: string | null;
  total_deaths: number | null;
  total_injuries: number | null;
};

export type IncidentDuplicateCandidate = {
  match_id: number;
  similarity_score: number;
  level: "medium";
  status: "pending";
  candidate: DuplicateCandidateIncident;
};

export type IncidentDuplicateDecision = "confirmed_duplicate" | "false_positive";

export type IncidentDuplicateResolutionResult = {
  decision: IncidentDuplicateDecision;
  incident_id: string;
  canonical_incident_id: string;
};
