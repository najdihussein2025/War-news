import type { CasualtyField, CasualtyFlagFilters, CasualtyFlagStatus, ResolutionEntry, ResolveFieldError } from "./types";

const statuses: CasualtyFlagStatus[] = ["open", "resolved", "dismissed", "auto_cleared"];

export const filtersFromSearch = (search: string): CasualtyFlagFilters => {
  const params = new URLSearchParams(search);
  const rawStatus = params.get("status") as CasualtyFlagStatus | null;
  return {
    status: rawStatus && statuses.includes(rawStatus) ? rawStatus : "open",
    reason: params.get("reason") || undefined,
    dateFrom: params.get("date_from") || undefined,
    dateTo: params.get("date_to") || undefined,
    q: params.get("q") || undefined,
  };
};

export const filtersToSearch = (filters: CasualtyFlagFilters, selected?: string) => {
  const params = new URLSearchParams();
  if (filters.status !== "open") params.set("status", filters.status);
  if (filters.reason) params.set("reason", filters.reason);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (selected) params.set("flag", selected);
  return params;
};

export const casualtyFields: CasualtyField[] = ["male_d", "female_d", "children_d", "total_deaths", "male_i", "female_i", "children_i", "total_injuries"];
export type AllocationValues = Record<string, Partial<Record<CasualtyField, string>>>;

export const assignedTotal = (values: AllocationValues, kind: CasualtyField) =>
  Object.values(values).reduce((sum, row) => sum + (row[kind] === undefined || row[kind] === "" ? 0 : Number(row[kind])), 0);

export const isOverTotal = (values: AllocationValues, kind: CasualtyField, total: number | null | undefined) =>
  typeof total === "number" && assignedTotal(values, kind) > total;

// Sibling locations of an aggregate toll that this save did not resolve, in panel order.
export const unresolvedSiblingIds = (
  siblingIds: string[],
  results: Array<{ incident_id: string; resolved: boolean }>,
) => {
  const resolved = new Set(results.filter((item) => item.resolved).map((item) => item.incident_id));
  return siblingIds.filter((incidentId) => !resolved.has(incidentId));
};

export const isWholeNonNegative = (value: string) => value === "" || /^\d+$/.test(value);

export const dismissReasonError = (reason: string) => reason.trim().length < 3 ? "Enter at least 3 characters." : undefined;

export const canSubmitResolution = (confirmedUnknown: boolean, entryCount: number, overTotal: boolean, unknownLocationCount = 0) =>
  !overTotal && (confirmedUnknown || entryCount > 0 || unknownLocationCount > 0);

export const buildResolutionEntries = (values: AllocationValues): ResolutionEntry[] => {
  const incidentIds = new Set(Object.keys(values));
  return [...incidentIds].flatMap((incident_id) => {
    const row = values[incident_id] ?? {};
    const entry: ResolutionEntry = { incident_id };
    for (const kind of casualtyFields) {
      if (row[kind] !== undefined && row[kind] !== "") entry[kind] = Number(row[kind]);
    }
    return Object.keys(entry).length > 1 ? [entry] : [];
  });
};

export const mapFieldErrors = (error: unknown): { fields: Record<string, string>; summary: string[] } => {
  const data = (error as { response?: { data?: { errors?: ResolveFieldError[]; detail?: { errors?: ResolveFieldError[] } } } })?.response?.data;
  const errors = data?.errors ?? data?.detail?.errors ?? [];
  const fields: Record<string, string> = {};
  const summary: string[] = [];
  for (const item of errors) {
    if (item.incident_id && casualtyFields.includes(item.field as CasualtyField)) fields[`${item.incident_id}.${item.field}`] = item.message;
    else summary.push(item.message);
  }
  return { fields, summary };
};

export const mapApiError = (error: unknown): string => {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response;
  const detail = response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => typeof item?.msg === "string" ? item.msg.replace(/^Value error, /, "") : "Invalid value").join(" ");
  }
  return "The request could not be saved. Try again.";
};
