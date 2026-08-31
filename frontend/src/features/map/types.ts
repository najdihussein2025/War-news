export type MapEventType = "incident" | "air_violation";

export type MapEvent = {
  id: string;
  event_type: MapEventType;
  category: string;
  title: string;
  summary: string;
  occurred_at: string;
  latitude: number;
  longitude: number;
  village: string | null;
  caza: string | null;
  source: string | null;
  detail_path: string | null;
};

export type MapEventResponse = {
  items: MapEvent[];
  unmapped_count: number;
  truncated: boolean;
};
