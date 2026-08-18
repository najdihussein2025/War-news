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
  khabar: string;
  source: IncidentSource;
  source_reference: string | null;
  matched: boolean;
  duplicate_flag: "none" | "possible";
  created_at: string;
};

export type IncidentListResponse = {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
};

export type IncidentFilters = {
  limit: number;
  offset: number;
  village?: string;
  sourceType?: string;
  eventDateFrom?: string;
  eventDateTo?: string;
  flaggedOnly?: boolean;
};

export type CasualtyDemographics = {
  male_d: number | null;
  male_i: number | null;
  female_d: number | null;
  female_i: number | null;
  children_d: number | null;
  children_i: number | null;
};

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
  event_time: string | null;
  casualty_demographics: CasualtyDemographics;
  lebanese_army: null;
  unifil: null;
  municipality: null;
  school_university: null;
  religious_cultural: null;
  hospital: null;
  health_center: null;
  emergency_civil_defense: null;
  press: null;
  government_building: null;
  road_bridge: null;
  vehicles: null;
  crossings_other: null;
  warning_classification: null;
};
