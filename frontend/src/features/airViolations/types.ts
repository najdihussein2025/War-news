export type AirViolation = {
  id: number;
  raw_message_id: number | null;
  condition_id: number;
  source_id: number;
  caza_en: string | null;
  caza_ar: string | null;
  village_en: string | null;
  village_ar: string | null;
  event_month: string | null;
  event_date: string;
  event_time: string | null;
  khabar: string;
  note_1: string | null;
  note_2: string | null;
  source_link: string | null;
  created_at: string;
  action_en: string;
  action_ar: string;
  source_name: string;
};

export type AirViolationListResponse = {
  items: AirViolation[];
  total: number;
  limit: number;
  offset: number;
};

export type AirViolationFilters = {
  limit: number;
  offset: number;
  conditionId?: string;
  eventDateFrom?: string;
  eventDateTo?: string;
  cazaEn?: string;
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
