import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { StatusBadge } from "../../../components/StatusBadge";
import type { Incident, IncidentBulletinGroup } from "../types";
import {
  ReasonChips,
  summarizeManyVerificationReasons,
  summarizeVerificationReasons,
} from "../verificationReasons";

const duplicateKeys = new Set(["duplicate", "cross_source_duplicate"]);

const incidentFlag = (incident: Incident) => {
  const summaries = summarizeVerificationReasons(incident.verification_reason);
  const labels = [
    ...summaries.map((summary) => summary.label),
    ...(incident.open_flags ?? []).map((flag) => flag.label || flag.summary || flag.reason_code),
  ].filter(Boolean);
  return {
    label: [...new Set(labels)].join(", "),
    signature: [...new Set(labels.map((label) => label.toLowerCase()))].sort().join("|"),
  };
};

export const incidentWarningLabels = (incidents: Incident[]) => {
  const flags = incidents.map(incidentFlag);
  const counts = new Map<string, number>();
  flags.forEach((flag) => counts.set(flag.signature, (counts.get(flag.signature) ?? 0) + 1));
  if (counts.size <= 1) return flags.map(() => "");
  const baseline = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  return flags.map((flag) => flag.signature && flag.signature !== baseline ? flag.label : "");
};

export const bulletinReasonPresentation = (group: IncidentBulletinGroup) => {
  const summaries = summarizeManyVerificationReasons(group.verification_reasons);
  const duplicateSummary = summaries.find((summary) => duplicateKeys.has(summary.key));
  const duplicateScore = duplicateSummary?.score ?? Math.max(
    ...group.incidents.map((incident) => incident.duplicate_similarity_score ?? -1),
  );
  const hasDuplicate = group.verification_types.includes("duplicate") || Boolean(duplicateSummary);
  const duplicatePrefix = duplicateSummary?.key === "cross_source_duplicate" ? "Cross-source dup" : "Duplicate";
  const duplicateLabel = hasDuplicate
    ? `${duplicatePrefix}${duplicateScore >= 0 ? ` · ${Math.round(duplicateScore * 100)}%` : ""}`
    : null;
  const hasCasualtyFlag = group.verification_types.some(
    (type) => type === "casualty_missing_number" || type === "casualty_aggregate_toll",
  );
  const hasChangedFlag = summaries.some((summary) => summary.key === "other") || (!hasDuplicate && !hasCasualtyFlag);

  return {
    duplicateLabel,
    hasCasualtyFlag,
    hasChangedFlag,
    chips: summaries.filter((summary) => !duplicateKeys.has(summary.key)),
  };
};

export const IncidentBulletinHeading = ({ group }: { group: IncidentBulletinGroup }) => {
  const presentation = bulletinReasonPresentation(group);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5" dir="ltr">
        <span className="font-semibold text-text-primary">Raw #{group.raw_message_id}</span>
        {presentation.duplicateLabel ? <StatusBadge label={presentation.duplicateLabel} variant="warning" /> : null}
        {presentation.hasCasualtyFlag ? <StatusBadge label="Casualties unassigned" variant="danger" /> : null}
        {presentation.hasChangedFlag ? <StatusBadge label="Changed after verification" variant="neutral" /> : null}
      </div>
      <p className="line-clamp-2 break-words text-small leading-6 text-text-primary" dir="rtl" lang="ar">
        {group.khabar}
      </p>
      <ReasonChips summaries={presentation.chips} />
    </div>
  );
};

const casualtyText = (incident: Incident) => {
  const deaths = incident.total_deaths ?? 0;
  const injuries = incident.total_injuries ?? 0;
  if (deaths === 0 && injuries === 0) return "no casualties";
  return `${deaths} ${deaths === 1 ? "death" : "deaths"} · ${injuries} ${injuries === 1 ? "injury" : "injuries"}`;
};

export const CompactIncidentList = ({ group }: { group: IncidentBulletinGroup }) => {
  const [expanded, setExpanded] = useState(false);
  const visibleIncidents = expanded ? group.incidents : group.incidents.slice(0, 3);
  const hiddenCount = group.incidents.length - visibleIncidents.length;
  const warningLabels = incidentWarningLabels(group.incidents);

  return (
    <div className="space-y-1">
      {visibleIncidents.map((incident, index) => (
        <div
          key={incident.id ?? `${group.raw_message_id}-${incident.village}-${incident.condition}`}
          className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5 leading-5"
        >
          <span className="font-semibold text-text-primary">{incident.village || "Unknown village"}</span>
          <span className="text-text-muted" aria-hidden="true">·</span>
          <span className="text-caption text-text-muted">{incident.condition || "No condition"}</span>
          <span className="text-text-muted" aria-hidden="true">·</span>
          <span className="text-caption text-text-muted">{casualtyText(incident)}</span>
          {warningLabels[index] ? (
            <span
              className="inline-flex h-2 w-2 shrink-0 rounded-full bg-warning"
              title={warningLabels[index]}
              aria-label={warningLabels[index]}
            />
          ) : null}
        </div>
      ))}
      {hiddenCount > 0 || expanded && group.incidents.length > 3 ? (
        <button
          type="button"
          className="rounded-sm text-caption font-semibold text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Show fewer incidents" : `+${hiddenCount} more incidents`}
        </button>
      ) : null}
    </div>
  );
};

type BulletinActionsProps = {
  disabled?: boolean;
  onOpen: () => void;
  onReject: () => void;
  onVerify: () => void;
};

const actionButtonClass = "h-8 whitespace-nowrap px-2.5 text-caption shadow-none hover:shadow-none";

export const IncidentBulletinActions = ({ disabled, onOpen, onReject, onVerify }: BulletinActionsProps) => (
  <div className="flex items-center justify-end gap-1.5 whitespace-nowrap" dir="ltr">
    <div className="hidden items-center gap-1.5 lg:flex">
      <Button type="button" variant="ghost" className={actionButtonClass} onClick={onOpen}>Open</Button>
      <Button type="button" variant="secondary" className={actionButtonClass} onClick={onReject}>Reject all</Button>
      <Button type="button" className={actionButtonClass} disabled={disabled} onClick={onVerify}>Verify all</Button>
    </div>
    <div className="flex items-center gap-1.5 lg:hidden">
      <Button type="button" className={actionButtonClass} disabled={disabled} onClick={onVerify}>Verify all</Button>
      <details className="relative">
        <summary
          className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-md border border-border bg-surface-raised text-body font-semibold text-text-primary hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          aria-label="More bulletin actions"
        >
          ⋯
        </summary>
        <div className="absolute right-0 z-20 mt-1 min-w-32 rounded-md border border-border bg-surface-raised p-1 shadow-lg" role="menu">
          <button type="button" className="block w-full rounded-sm px-3 py-2 text-left text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring" role="menuitem" onClick={onOpen}>Open</button>
          <button type="button" className="block w-full rounded-sm px-3 py-2 text-left text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring" role="menuitem" onClick={onReject}>Reject all</button>
        </div>
      </details>
    </div>
  </div>
);
