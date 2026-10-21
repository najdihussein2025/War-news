export type Level = "mohafaza" | "caza" | "village";
export type Metric = "incidents" | "deaths" | "injuries" | "casualties" | "breaches";
export type Grain = "day" | "week" | "month";

export type AnalyticsFilters = {
  /** Range preset id: "7d" | "30d" | "all" | "m:YYYY-MM" | "custom". */
  range: string;
  dateFrom: string;
  dateTo: string;
  level: Level;
  families: string[];
  metric: Metric;
  includePending: boolean;
  areaCode: string | null;
  /** Air-violation condition id when metric is breaches (null = all types). */
  airType: number | null;
};

export type Family = {
  code: string;
  name_en: string;
  name_ar: string;
  sort_order: number;
  is_air_violation: boolean;
  counts_in_headline: boolean;
};

export type MetaResponse = {
  incident_data: { first_date: string | null; last_date: string | null };
  air_data: { first_date: string | null; last_date: string | null };
  archive: { cutoff_date: string | null; batches: Array<{ archive_batch: string; archived_at: string; incidents: number }> };
  families: Family[];
  area_counts: Record<string, number>;
  last_refresh: string | null;
  refresh_queue: number;
  pending_review: { incidents: number; live: number };
  air_conditions: Record<string, string>;
  air_level_conditions: Record<Level, number[]>;
};

export type MapValue = { code: string; value: number; families?: Record<string, number> };
export type MapResponse = {
  level: Level;
  metric: Metric;
  values: MapValue[];
  unit_note: string;
  unsupported_air_levels: Record<string, number[]>;
};

export type Delta = { current: number; previous: number; delta: number; pct: number | null };
export type Split = { male: number; female: number; children: number; unspecified: number };
export type SeriesPoint = { date: string; value: number };

export type KpisResponse = {
  period: { date_from: string; date_to: string; previous_from: string; previous_to: string; days: number };
  incidents: Delta;
  deaths: Delta & Split;
  injuries: Delta & Split;
  villages_affected: Delta;
  cazas_affected: Delta;
  air_breaches: Delta & { by_type: Array<{ condition_id: number; label: string; current: number; previous: number }> };
  pending_review: number;
  casualty_completeness: CasualtyCompleteness;
  unattributed_shared_toll_incidents: number;
  escalation: { today: number; date: string; rolling_30d_daily_average: number; ratio: number | null };
  sparklines: { incidents: SeriesPoint[]; deaths: SeriesPoint[]; injuries: SeriesPoint[]; breaches: SeriesPoint[] };
};

export type TimelineSeries = { key: string; label_en: string; label_ar: string | null; total: number; points: SeriesPoint[] };
export type TimelineResponse = {
  grain: Grain;
  metric: Metric;
  series: TimelineSeries[];
  total: SeriesPoint[];
  moving_average_7d: SeriesPoint[];
  coverage: { available: boolean; note: string; gap_dates: string[]; flagged: CoverageFlag[] };
};

export type RankingRow = {
  code: string;
  /** Position by the selected metric (DESC, ties by name), fixed by the API. */
  rank: number;
  level: Level;
  name_en: string | null;
  name_ar: string | null;
  parent_name_en: string | null;
  parent_name_ar: string | null;
  value: number;
  incidents?: number;
  deaths?: number;
  injuries?: number;
  breaches?: number;
  first_date: string | null;
  last_date: string | null;
  dominant_family?: string;
  dominant_condition_label?: string | null;
};
export type RankingsResponse = { level: Level; metric: Metric; limit: number; rows: RankingRow[] };

export type PeakEntry = { start: string; value: number; low_coverage_days: number; top_areas: Array<{ code: string; name_en: string; name_ar: string; value: number }> } | null;
export type PeaksResponse = Record<"incidents" | "deaths" | "breaches", { day: PeakEntry; week: PeakEntry }>;

export type MatrixResponse = {
  metric: Metric;
  columns: Family[];
  rows: Array<{ code: string; name_en: string; name_ar: string; mohafaza_code: string; cells: Record<string, number>; total: number }>;
  column_totals: Record<string, number>;
  grand_total: number;
};

export type AreaResponse = {
  area: { code: string; level: Level; name_en: string; name_ar: string; parent_name_en: string | null; parent_name_ar: string | null; area_km2: number | null; is_disputed: boolean; center_lat: number | null; center_lon: number | null };
  totals: Record<string, number>;
  pending_review: number;
  casualty_completeness: CasualtyCompleteness;
  air_breaches: { total: number; by_type: Array<{ condition_id: number; label: string; value: number }> };
  families: Array<{ code: string; name_en: string; name_ar: string; incidents: number; deaths: number; injuries: number }>;
  timeline: { incidents: SeriesPoint[]; breaches: SeriesPoint[] };
  top_children: { level: Level | null; rows: RankingRow[] };
  first_last_hit: { first_date: string | null; last_date: string | null };
};

export type DrilldownItem = {
  id: string;
  event_date: string;
  event_time: string | null;
  village_en: string | null;
  village_ar: string | null;
  action_en: string;
  action_ar: string;
  family: string;
  verification_status: string;
  bucket: "counted" | "pending";
  source: "live" | "archive";
  deaths: number;
  injuries: number;
  khabar_excerpt: string;
};
export type DrilldownResponse = { page: number; page_size: number; total: number; items: DrilldownItem[] };

export type CasualtyCompleteness = { incidents: number; with_status: number; pct: number | null };
export type CoverageStatus = "ok" | "low" | "none" | "unknown";
export type CoverageFlag = { date: string; status: CoverageStatus; messages: number };
export type CoverageDay = { date: string; messages: number; baseline: number | null; status: CoverageStatus; sources: Record<string, number> };
export type CoverageResponse = { low_ratio: number; note: string; days: CoverageDay[]; low_days: number; no_coverage_days: number };
