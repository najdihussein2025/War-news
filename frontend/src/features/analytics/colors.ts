/** Stable colors from design-system/war-news-analytics/MASTER.md. */
export const FAMILY_COLORS: Record<string, string> = {
  airstrikes: "#d55e00",
  drone_strikes: "#0072b2",
  artillery: "#cc79a7",
  flares_phosphorus: "#e69f00",
  demolitions: "#8c5a2b",
  gunfire: "#009e73",
  incursions: "#56b4e9",
  air_violations: "#082d6f",
  other: "#7f8c8d",
  unclassified: "#b9aec9",
};
export const AIR_TYPE_COLORS: Record<string, string> = { "34": "#56b4e9", "35": "#082d6f", "36": "#0072b2", "38": "#e69f00" };
export const familyColor = (code: string): string => FAMILY_COLORS[code] ?? "#7f8c8d";

/** ColorBrewer YlOrRd-7, light to dark. */
export const SEQUENTIAL = ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026"] as const;
export const NO_DATA_COLOR = "#e6ebf0";
export const DISPUTED_LINE = "#8ca0af";

/**
 * Quantile class upper bounds. Class i holds values in (breaks[i-1], breaks[i]].
 * With few distinct values each distinct value is its own class.
 */
export const quantileBreaks = (values: number[], classes = 7): number[] => {
  const sorted = values.filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  const distinct = Array.from(new Set(sorted));
  if (distinct.length <= classes) return distinct;
  const breaks: number[] = [];
  for (let i = 1; i <= classes; i += 1) {
    const idx = Math.min(sorted.length - 1, Math.ceil((i / classes) * sorted.length) - 1);
    const value = sorted[idx];
    if (breaks[breaks.length - 1] !== value) breaks.push(value);
  }
  return breaks;
};

export const classIndex = (value: number, breaks: number[]): number => {
  if (!breaks.length || !(value > 0)) return -1;
  for (let i = 0; i < breaks.length; i += 1) if (value <= breaks[i]) return i;
  return breaks.length - 1;
};

/** Palette color of class `index` out of `count` classes, spread over the 7 steps. */
export const classColor = (index: number, count: number): string => {
  if (index < 0 || count <= 0) return NO_DATA_COLOR;
  if (count === 1) return SEQUENTIAL[5];
  const step = Math.round((index * (SEQUENTIAL.length - 1)) / (count - 1));
  return SEQUENTIAL[step];
};

export const colorForValue = (value: number, breaks: number[]): string =>
  classColor(classIndex(value, breaks), breaks.length);

export type LegendEntry = { color: string; from: number; to: number };

export const legendEntries = (breaks: number[]): LegendEntry[] =>
  breaks.map((upper, i) => ({
    color: classColor(i, breaks.length),
    from: i === 0 ? 1 : Math.floor(breaks[i - 1]) + 1,
    to: upper,
  }));

/** Readable text color for a given sequential background. */
export const textOn = (hex: string): string => {
  const n = Number.parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#0b2236" : "#ffffff";
};

/* ------------------------------------------------------------------ map scales (v2)
 * Few, very unequal areas (8 mohafazat, 26 cazas): a linear scale from 0 to max, so a
 * small value stays pale next to a large one (quantiles made ~30 look like ~280). Many
 * villages: quantile classes, with the legend showing the real min-max of each class. */
export type MapScale =
  | { kind: "linear"; max: number }
  | { kind: "quantile"; breaks: number[]; legend: LegendEntry[] };

export const scaleKindFor = (level: "mohafaza" | "caza" | "village"): MapScale["kind"] =>
  level === "village" ? "quantile" : "linear";

const hexToRgb = (hex: string): [number, number, number] => {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgbToHex = (rgb: number[]): string => `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;

/** Continuous color for t in [0, 1] along the sequential palette. */
export const interpolateSequential = (t: number): string => {
  const x = Math.min(1, Math.max(0, t)) * (SEQUENTIAL.length - 1);
  const i = Math.min(SEQUENTIAL.length - 2, Math.floor(x));
  const a = hexToRgb(SEQUENTIAL[i]);
  const b = hexToRgb(SEQUENTIAL[i + 1]);
  const f = x - i;
  return rgbToHex(a.map((c, k) => c + (b[k] - c) * f));
};

/** Legend classes built from the values actually in each class (real ranges, empty classes dropped). */
export const quantileLegend = (values: number[], breaks: number[]): LegendEntry[] => {
  const members: number[][] = breaks.map(() => []);
  values.forEach((v) => {
    const i = classIndex(v, breaks);
    if (i >= 0) members[i].push(v);
  });
  return members
    .map((m, i) => (m.length ? { color: classColor(i, breaks.length), from: Math.min(...m), to: Math.max(...m) } : null))
    .filter((e): e is LegendEntry => e !== null);
};

export const buildScale = (level: "mohafaza" | "caza" | "village", values: number[]): MapScale => {
  const positive = values.filter((v) => Number.isFinite(v) && v > 0);
  if (scaleKindFor(level) === "linear") return { kind: "linear", max: positive.length ? Math.max(...positive) : 0 };
  const breaks = quantileBreaks(positive);
  return { kind: "quantile", breaks, legend: quantileLegend(positive, breaks) };
};

export const scaleColor = (scale: MapScale, value: number): string => {
  if (!(value > 0)) return NO_DATA_COLOR;
  if (scale.kind === "linear") return scale.max > 0 ? interpolateSequential(value / scale.max) : NO_DATA_COLOR;
  return colorForValue(value, scale.breaks);
};

/** Tick values for the linear legend bar: 0, the middle and the max (integers, distinct). */
export const linearTicks = (max: number): number[] =>
  max <= 0 ? [0] : Array.from(new Set([0, Math.round(max / 2), max]));
