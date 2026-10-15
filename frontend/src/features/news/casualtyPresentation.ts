type CasualtySummary = {
  killed: number | null;
  injured: number | null;
  breakdown?: Record<string, number>;
  status?: string | null;
  verification_reason?: string | null;
};

const countLabel = (value: number, singular: string, plural: string) =>
  `${value} ${value === 1 ? singular : plural}`;

export const casualtyHeadline = (casualties: CasualtySummary): string => {
  const hasOrphanBreakdown = Object.values(casualties.breakdown ?? {}).some((value) => value != null)
    && casualties.killed == null && casualties.injured == null;
  if (hasOrphanBreakdown) return "Casualty data needs check";
  if (casualties.status === "explicit_none") return "No casualties (stated)";
  if (casualties.status === "mentioned_no_number") return "Casualties mentioned, number not given";
  if (casualties.status === "needs_verification" && casualties.verification_reason?.includes("approximate casualty count")) {
    const match = casualties.verification_reason.match(/(?:اكثر|أكثر)\s+من\s+(\d+|[٠-٩]+)\s+(جريح|مصاب)/u);
    if (match) return `More than ${match[1]} injured (approximate)`;
  }
  if (casualties.killed == null && casualties.injured == null) return "No casualties reported";
  return [
    casualties.killed == null ? null : countLabel(casualties.killed, "killed", "killed"),
    casualties.injured == null ? null : countLabel(casualties.injured, "injured", "injured"),
  ].filter(Boolean).join(" · ");
};

export const casualtyChip = (key: string, value: number): string => {
  const [group, outcome] = key.split("_");
  const noun = group === "children" ? (value === 1 ? "child" : "children")
    : group === "women" ? (value === 1 ? "woman" : "women")
      : value === 1 ? "man" : "men";
  return `${value} ${noun} ${outcome}`;
};

export const compactCasualtyText = (deaths: number | null, injuries: number | null) => {
  if (deaths == null && injuries == null) return "—";
  if ((deaths ?? 0) === 0 && (injuries ?? 0) === 0) return "no casualties (stated)";
  return [
    deaths == null ? null : countLabel(deaths, "death", "deaths"),
    injuries == null ? null : countLabel(injuries, "injury", "injuries"),
  ].filter(Boolean).join(" · ");
};
