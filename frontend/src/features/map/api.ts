import { apiClient } from "../../lib/apiClient";
import type { MapEventResponse, MapEventType } from "./types";

export const getMapEvents = async (filters: {
  dateFrom?: string;
  dateTo?: string;
  eventTypes: MapEventType[];
}): Promise<MapEventResponse> => {
  const params = new URLSearchParams();
  if (filters.dateFrom) params.set("event_date_from", filters.dateFrom);
  if (filters.dateTo) params.set("event_date_to", filters.dateTo);
  filters.eventTypes.forEach((eventType) => params.append("event_type", eventType));
  const response = await apiClient.get<MapEventResponse>(`/map/events?${params.toString()}`);
  return response.data;
};
