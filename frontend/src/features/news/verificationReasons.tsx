import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "../../components/StatusBadge";
import type { Incident, IncidentDetail } from "./types";

export type ReasonKey =
  | "duplicate"
  | "cross_source_duplicate"
  | "low_confidence_village"
  | "no_condition_match"
  | "flare_strike_wording"
  | "casualties_not_per_village"
  | "other";

export type VerificationReasonSummary = {
  key: ReasonKey;
  label: string;
  score?: number;
  matchedIncidentId?: string;
  fragments: string[];
};

const LABELS: Record<ReasonKey, string> = {
  duplicate: "Duplicate",
  cross_source_duplicate: "Cross-source duplicate",
  low_confidence_village: "Low-confidence village",
  no_condition_match: "No condition match",
  flare_strike_wording: "Flare + strike wording",
  casualties_not_per_village: "Casualties not per-village",
  other: "Needs review",
};

const splitReasonText = (raw: string) =>
  raw
    .split(/\s+\|\s+|;\s+|\. ;\s*|\.;\s*/g)
    .map((fragment) => fragment.trim())
    .filter(Boolean);

const scoreFromText = (text: string) => {
  const percent = text.match(/(\d+(?:\.\d+)?)\s*%/);
  if (percent) return Number(percent[1]) / 100;
  const score = text.match(/\bscore\s*[:=]?\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+)\b/i);
  return score ? Number(score[1]) : undefined;
};

const matchedIncidentIdFromText = (text: string) => {
  const match = text.match(/\b(?:incident|match|id)\s*#?\s*([a-f0-9-]{6,}|\d{2,})\b/i);
  return match?.[1];
};

const keyForFragment = (fragment: string): ReasonKey => {
  const text = fragment.toLowerCase();
  if (text.includes("cross-source") || text.includes("cross source") || text.includes("other source")) {
    return "cross_source_duplicate";
  }
  if (text.includes("duplicate") || text.includes("similarity") || text.includes("score")) {
    return "duplicate";
  }
  if (text.includes("low confidence") || text.includes("village match") || text.includes("village") && text.includes("confidence")) {
    return "low_confidence_village";
  }
  if (text.includes("no condition") || text.includes("condition match")) {
    return "no_condition_match";
  }
  if ((text.includes("flare") || text.includes("phosph")) && (text.includes("strike") || text.includes("raid"))) {
    return "flare_strike_wording";
  }
  if (text.includes("casualt") || text.includes("death") || text.includes("injur")) {
    if (text.includes("per-village") || text.includes("per village") || text.includes("aggregate") || text.includes("unassigned")) {
      return "casualties_not_per_village";
    }
  }
  return "other";
};

export const summarizeVerificationReasons = (raw: string | null | undefined): VerificationReasonSummary[] => {
  const fragments = splitReasonText(raw ?? "");
  if (!fragments.length) return [];

  const byKey = new Map<ReasonKey, VerificationReasonSummary>();
  for (const fragment of fragments) {
    const key = keyForFragment(fragment);
    const score = scoreFromText(fragment);
    const existing = byKey.get(key);
    const matchedIncidentId = matchedIncidentIdFromText(fragment);
    if (!existing) {
      byKey.set(key, {
        key,
        label: key === "duplicate" && score != null ? `${LABELS[key]} · ${Math.round(score * 100)}%` : LABELS[key],
        score,
        matchedIncidentId,
        fragments: [fragment],
      });
      continue;
    }
    existing.fragments.push(fragment);
    if (score != null && (existing.score == null || score > existing.score)) {
      existing.score = score;
      existing.label = key === "duplicate" ? `${LABELS[key]} · ${Math.round(score * 100)}%` : LABELS[key];
    }
    if (!existing.matchedIncidentId && matchedIncidentId) {
      existing.matchedIncidentId = matchedIncidentId;
    }
  }

  return [...byKey.values()];
};

export const summarizeManyVerificationReasons = (reasons: Array<string | null | undefined>) => {
  const byKey = new Map<ReasonKey, VerificationReasonSummary>();
  for (const reason of reasons) {
    for (const summary of summarizeVerificationReasons(reason)) {
      const existing = byKey.get(summary.key);
      if (!existing) {
        byKey.set(summary.key, { ...summary, fragments: [...summary.fragments] });
        continue;
      }
      existing.fragments.push(...summary.fragments);
      if (summary.score != null && (existing.score == null || summary.score > existing.score)) {
        existing.score = summary.score;
        existing.label = summary.key === "duplicate" ? `${LABELS[summary.key]} · ${Math.round(summary.score * 100)}%` : LABELS[summary.key];
      }
      if (!existing.matchedIncidentId && summary.matchedIncidentId) {
        existing.matchedIncidentId = summary.matchedIncidentId;
      }
    }
  }
  return [...byKey.values()];
};

export const ReasonChips = ({ summaries, max = 2 }: { summaries: VerificationReasonSummary[]; max?: number }) => {
  const visible = summaries.slice(0, max);
  const hidden = summaries.slice(max);
  return (
    <div className="flex flex-wrap gap-1.5" dir="ltr">
      {visible.map((summary) => (
        <span key={summary.key} aria-label={summary.label}>
          <StatusBadge label={summary.label} variant="warning" />
        </span>
      ))}
      {hidden.length ? (
        <span title={hidden.map((summary) => summary.label).join("\n")} aria-label={hidden.map((summary) => summary.label).join(", ")}>
          <StatusBadge label={`+${hidden.length}`} variant="warning" />
        </span>
      ) : null}
    </div>
  );
};

const detailLine = (summary: VerificationReasonSummary, link?: ReactNode) => {
  if (summary.key === "duplicate") {
    return (
      <>
        Looks like a duplicate{link ? <> of {link}</> : ""}{summary.score == null ? "" : ` (similarity ${Math.round(summary.score * 100)}%)`}.
      </>
    );
  }
  if (summary.key === "cross_source_duplicate") return "Looks like the same incident from another source.";
  if (summary.key === "low_confidence_village") return "Village match is low confidence - check the village name.";
  if (summary.key === "no_condition_match") return "No condition matched from the text.";
  if (summary.key === "flare_strike_wording") return "Message mentions both flare bombs and strikes - confirm both happened.";
  if (summary.key === "casualties_not_per_village") return "Casualties are not clearly assigned per village.";
  return "Needs human review.";
};

export const WhyNeedsReviewSection = ({
  incident,
  roleBase,
  search,
}: {
  incident: IncidentDetail;
  roleBase: string;
  search: string;
}) => {
  const summaries = summarizeVerificationReasons(incident.verification_reason);
  if (!summaries.length && !incident.verification_reason) return null;

  return (
    <section className="rounded-lg border border-warning/40 bg-surface-raised p-5">
      <h2 className="text-h4 font-semibold text-text-primary">Why this needs review</h2>
      <p className="mt-3 whitespace-pre-wrap text-right text-body leading-8 text-text-primary" dir="rtl" lang="ar">
        {incident.khabar}
      </p>
      <div className="mt-5 space-y-4 border-t border-border pt-5">
        <article className="rounded-md border border-border bg-surface p-4">
          <h3 className="text-small font-semibold text-text-primary">
            {incident.village || "Unknown village"} · {incident.condition || "No condition"}
          </h3>
          {summaries.length ? (
            <ul className="mt-3 space-y-2 text-small text-text-muted">
              {summaries.map((summary) => {
                const link = summary.matchedIncidentId ? (
                  <Link className="font-semibold text-accent hover:text-accent-hover" to={`${roleBase}/incidents/${summary.matchedIncidentId}${search}`}>
                    incident #{summary.matchedIncidentId}
                  </Link>
                ) : undefined;
                return <li key={summary.key}>{detailLine(summary, link)}</li>;
              })}
            </ul>
          ) : (
            <p className="mt-3 text-small text-text-muted">Needs human review.</p>
          )}
        </article>
      </div>
      {incident.verification_reason ? (
        <details className="mt-4 rounded-md border border-border bg-surface p-3">
          <summary className="cursor-pointer text-small font-semibold text-text-primary">Raw reason text</summary>
          <p className="mt-2 whitespace-pre-wrap text-caption text-text-muted">{incident.verification_reason}</p>
        </details>
      ) : null}
    </section>
  );
};

export const incidentHasVerificationFlag = (incident: Incident) =>
  Boolean(incident.verification_reason || incident.verification_status === "needs_verification" || (incident.open_flags ?? []).length);
