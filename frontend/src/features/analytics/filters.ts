import type { AnalyticsFilters, Level, Metric } from "./types";

export const LEVELS: Level[] = ["mohafaza", "caza", "village"];
export const METRICS: Metric[] = ["incidents", "deaths", "injuries", "casualties", "breaches"];
export const MAX_RANGE_DAYS = 400;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MONTH_RE = /^m:(\d{4})-(\d{2})$/;

const addDays = (iso: string, days: number): string => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days, 12)).toISOString().slice(0, 10);
};

export const daysBetween = (from: string, to: string): number => {
  const a = Date.parse(`${from}T12:00:00Z`);
  const b = Date.parse(`${to}T12:00:00Z`);
  return Math.round((b - a) / 86_400_000) + 1;
};

export type RangeContext = { today: string; dataFirst: string | null; dataLast: string | null };

/** Resolve a range preset id to concrete dates. Never exceeds MAX_RANGE_DAYS. */
export const resolveRange = (
  range: string,
  ctx: RangeContext,
  custom?: { from: string; to: string },
): { from: string; to: string } => {
  const end = ctx.today;
  if (range === "7d") return { from: addDays(end, -6), to: end };
  if (range === "all") {
    const first = ctx.dataFirst ?? addDays(end, -29);
    const floor = addDays(end, -(MAX_RANGE_DAYS - 1));
    return { from: first < floor ? floor : first, to: end };
  }
  const month = MONTH_RE.exec(range);
  if (month) {
    const y = Number(month[1]);
    const m = Number(month[2]);
    const from = `${month[1]}-${month[2]}-01`;
    const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
    return { from, to: last > end ? end : last };
  }
  if (range === "custom" && custom && DATE_RE.test(custom.from) && DATE_RE.test(custom.to)) {
    return custom.from <= custom.to ? custom : { from: custom.to, to: custom.from };
  }
  return { from: addDays(end, -29), to: end }; // "30d" and any unknown value
};

export const defaultFilters = (today: string): AnalyticsFilters => ({
  range: "30d",
  dateFrom: addDays(today, -29),
  dateTo: today,
  level: "mohafaza",
  families: [],
  metric: "incidents",
  includePending: false,
  areaCode: null,
  airType: null,
});

/** URL query string -> filters. Unknown or malformed values fall back to defaults. */
export const parseFilters = (search: URLSearchParams, ctx: RangeContext): AnalyticsFilters => {
  const base = defaultFilters(ctx.today);
  const range = search.get("range") ?? base.range;
  const from = search.get("from") ?? "";
  const to = search.get("to") ?? "";
  const resolved = resolveRange(range, ctx, { from, to });
  const level = search.get("level") as Level;
  const metric = search.get("metric") as Metric;
  const air = Number(search.get("air"));
  return {
    range: range === "custom" && !(DATE_RE.test(from) && DATE_RE.test(to)) ? "30d" : range,
    dateFrom: resolved.from,
    dateTo: resolved.to,
    level: LEVELS.includes(level) ? level : base.level,
    families: search.getAll("family").filter(Boolean),
    metric: METRICS.includes(metric) ? metric : base.metric,
    includePending: search.get("pending") === "1",
    areaCode: search.get("area") || null,
    airType: Number.isInteger(air) && air > 0 ? air : null,
  };
};

/** filters -> URL query string; defaults are omitted so shared links stay short. */
export const serializeFilters = (f: AnalyticsFilters, today: string): URLSearchParams => {
  const p = new URLSearchParams();
  const def = defaultFilters(today);
  if (f.range !== def.range) p.set("range", f.range);
  if (f.range === "custom") {
    p.set("from", f.dateFrom);
    p.set("to", f.dateTo);
  }
  if (f.level !== def.level) p.set("level", f.level);
  f.families.forEach((family) => p.append("family", family));
  if (f.metric !== def.metric) p.set("metric", f.metric);
  if (f.includePending) p.set("pending", "1");
  if (f.areaCode) p.set("area", f.areaCode);
  if (f.metric === "breaches" && f.airType) p.set("air", String(f.airType));
  return p;
};

/** filters -> /api/analytics query string. */
export const toApiParams = (f: AnalyticsFilters, overrides: Partial<AnalyticsFilters> = {}): URLSearchParams => {
  const v = { ...f, ...overrides };
  const p = new URLSearchParams();
  p.set("date_from", v.dateFrom);
  p.set("date_to", v.dateTo);
  p.set("level", v.level);
  p.set("metric", v.metric);
  if (v.areaCode) p.set("area_code", v.areaCode);
  v.families.forEach((family) => p.append("family", family));
  if (v.metric === "breaches" && v.airType) p.set("condition_id", String(v.airType));
  if (v.includePending) p.set("include_pending", "true");
  return p;
};

export const sameFilters = (a: AnalyticsFilters, b: AnalyticsFilters): boolean =>
  JSON.stringify(a) === JSON.stringify(b);
