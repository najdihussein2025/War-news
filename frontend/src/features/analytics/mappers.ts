import type { CoverageStatus, Delta, DrilldownItem, MapResponse, SeriesPoint, TimelineResponse } from "./types";

/** Copy shared by chart tooltips and the visible coverage key. */
export const coverageWarning = (status: CoverageStatus | undefined): string | null => {
  if (status === "none") return "No ingested messages: reported values may be incomplete.";
  if (status === "low") return "Low message coverage: reported values may be incomplete.";
  return null;
};

export const formatNumber = (value: number | null | undefined): string =>
  value === null || value === undefined ? "–" : new Intl.NumberFormat("en-US").format(value);

export const formatPct = (pct: number | null): string =>
  pct === null ? "n/a" : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;

export type DeltaView = { text: string; direction: "up" | "down" | "flat"; label: string };

export const deltaView = (d: Delta): DeltaView => {
  const direction = d.delta > 0 ? "up" : d.delta < 0 ? "down" : "flat";
  const sign = d.delta > 0 ? "+" : "";
  const pct = d.pct === null ? "" : ` (${formatPct(d.pct)})`;
  return {
    direction,
    text: `${sign}${formatNumber(d.delta)}${pct}`,
    label: `${d.delta === 0 ? "No change" : d.delta > 0 ? "Up" : "Down"} ${formatNumber(Math.abs(d.delta))} vs previous period (${formatNumber(d.previous)})`,
  };
};

export const mapValueIndex = (map: MapResponse | undefined): Map<string, number> =>
  new Map((map?.values ?? []).map((v) => [v.code, v.value]));

export const sparkPath = (points: SeriesPoint[], width: number, height: number): string => {
  if (points.length === 0) return "";
  const max = Math.max(...points.map((p) => p.value), 1);
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  return points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(height - (p.value / max) * (height - 2) - 1).toFixed(1)}`)
    .join(" ");
};

/** Zero-fill a sparse series over [from, to] so charts show gaps as zero bars. */
export const fillDays = (points: SeriesPoint[], from: string, to: string): SeriesPoint[] => {
  const byDate = new Map(points.map((p) => [p.date, p.value]));
  const out: SeriesPoint[] = [];
  const end = Date.parse(`${to}T12:00:00Z`);
  for (let t = Date.parse(`${from}T12:00:00Z`); t <= end; t += 86_400_000) {
    const date = new Date(t).toISOString().slice(0, 10);
    out.push({ date, value: byDate.get(date) ?? 0 });
  }
  return out;
};

/** Arabic text must render right-to-left per element. */
export const hasArabic = (text: string | null | undefined): boolean => /[؀-ۿ]/.test(text ?? "");

export const villageLabel = (item: Pick<DrilldownItem, "village_en" | "village_ar">): string =>
  item.village_en || item.village_ar || "Unknown village";

/** Peak annotations for the timeline: index and value of the highest bar. */
export const peakOf = (timeline: TimelineResponse | undefined): { index: number; value: number } | null => {
  if (!timeline || timeline.total.length === 0) return null;
  let best = 0;
  timeline.total.forEach((p, i) => {
    if (p.value > timeline.total[best].value) best = i;
  });
  return timeline.total[best].value > 0 ? { index: best, value: timeline.total[best].value } : null;
};

/** Playback frames: one per day for short ranges, one per week otherwise (max 120 frames). */
export const playbackFrames = (from: string, to: string): Array<{ from: string; to: string }> => {
  const dayMs = 86_400_000;
  const start = Date.parse(`${from}T12:00:00Z`);
  const end = Date.parse(`${to}T12:00:00Z`);
  const days = Math.round((end - start) / dayMs) + 1;
  const step = days <= 120 ? 1 : 7;
  const frames: Array<{ from: string; to: string }> = [];
  for (let t = start; t <= end; t += step * dayMs) {
    const frameEnd = Math.min(t + (step - 1) * dayMs, end);
    frames.push({ from: new Date(t).toISOString().slice(0, 10), to: new Date(frameEnd).toISOString().slice(0, 10) });
  }
  return frames;
};
