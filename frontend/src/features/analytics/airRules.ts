import type { Level } from "./types";

/** Mirror of app/analytics/constants.py AIR_LEVEL_CONDITIONS (agreed decision 5). */
export const AIR_LEVEL_CONDITIONS: Record<Level, number[]> = {
  mohafaza: [34, 35, 36, 38],
  caza: [34, 36, 38],
  village: [38],
};

export const AIR_TYPES: Array<{ id: number; label: string; rule: string }> = [
  { id: 34, label: "Spy balloons", rule: "Spy balloons are counted per caza." },
  { id: 35, label: "Warplanes", rule: "Warplane breaches are counted per mohafaza in anchored 10-minute windows and are never split below mohafaza." },
  { id: 36, label: "Drones / surveillance", rule: "Drone breaches are counted per caza (6-hour windows in listed cazas, otherwise once per day), so they cannot be shown per village." },
  { id: 38, label: "Helicopters", rule: "Helicopters are counted per village." },
];

export const airTypeLabel = (id: number): string => AIR_TYPES.find((t) => t.id === id)?.label ?? String(id);

/** Reason a level button must be disabled for the chosen air type, or null when it is allowed. */
export const levelDisabledReason = (level: Level, airType: number | null, metricIsBreaches: boolean): string | null => {
  if (!metricIsBreaches || airType === null) return null;
  if (AIR_LEVEL_CONDITIONS[level].includes(airType)) return null;
  const type = AIR_TYPES.find((t) => t.id === airType);
  return `${type?.label ?? "This air type"} cannot be shown at ${level} level. ${type?.rule ?? ""}`.trim();
};

/** Air types left out of the map for `level` when no single type is chosen. */
export const excludedAirTypes = (level: Level): number[] =>
  AIR_LEVEL_CONDITIONS.mohafaza.filter((id) => !AIR_LEVEL_CONDITIONS[level].includes(id));

/** Pick the closest allowed level when the current one becomes unsupported. */
export const nearestSupportedLevel = (level: Level, airType: number | null): Level => {
  if (airType === null || AIR_LEVEL_CONDITIONS[level].includes(airType)) return level;
  const order: Level[] = ["village", "caza", "mohafaza"];
  const from = order.indexOf(level);
  for (let i = from + 1; i < order.length; i += 1) {
    if (AIR_LEVEL_CONDITIONS[order[i]].includes(airType)) return order[i];
  }
  return "mohafaza";
};
