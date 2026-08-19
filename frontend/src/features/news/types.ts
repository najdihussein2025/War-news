export type IncidentSource =
  | "Telegram"
  | "API"
  | "Manual"
  | "Twitter"
  | "Facebook"
  | "Website"
  | "Other";

export type Incident = {
  id: string;
  raw_message_id: number | null;
  village: string | null;
  condition: string;
  event_date: string;
  event_time: string | null;
  khabar: string;
  source: IncidentSource;
  source_reference: string | null;
  matched: boolean;
  duplicate_flag: "none" | "possible";
  details_pending: boolean;
  created_at: string;
};

export type IncidentListResponse = {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
  latest_incident_at: string | null;
};

export type IncidentFilters = {
  limit: number;
  offset: number;
  village?: string;
  condition?: string;
  sourceType?: string;
  eventDateFrom?: string;
  eventDateTo?: string;
  flaggedOnly?: boolean;
  verificationStatus?: "matched" | "needs_verification";
  duplicateOnly?: boolean;
};

export type CasualtyDemographics = {
  male_d: number | null;
  male_i: number | null;
  female_d: number | null;
  female_i: number | null;
  children_d: number | null;
  children_i: number | null;
};

export type IncidentCategorySection = Record<string, number | string>;

export type IncidentDetail = Incident & {
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
  casualty_demographics: CasualtyDemographics;
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
