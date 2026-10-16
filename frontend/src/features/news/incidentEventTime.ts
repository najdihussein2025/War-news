import type { Incident } from "./types";

export const incidentEventTime = (row: Pick<Incident, "event_time" | "summary_window_start" | "summary_window_end">): string => {
  if (row.event_time) return row.event_time.slice(0, 5);
  return "Exact time not stated";
};
