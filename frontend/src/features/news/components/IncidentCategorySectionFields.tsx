import { labelFor } from "../fieldLabels";
import { formatIncidentFieldValue } from "../formatIncidentFieldValue";
import type { IncidentCategorySectionKey } from "../incidentCategorySections";
import { fieldGroupForSection } from "../incidentCategorySections";
import type { IncidentDetails } from "../incidentSchema";
import { isReported } from "../incidentSchema";

type Props = {
  sectionKey: IncidentCategorySectionKey;
  details: IncidentDetails;
};

const valueClassName = (emphasis?: "deaths" | "injuries") => {
  if (emphasis === "deaths") {
    return "mt-1 text-small font-semibold text-danger";
  }
  if (emphasis === "injuries") {
    return "mt-1 text-small font-semibold text-warning";
  }
  return "mt-1 text-small font-semibold text-text-primary";
};

export const IncidentCategorySectionFields = ({ sectionKey, details }: Props) => {
  const group = fieldGroupForSection(sectionKey);
  if (!group) {
    return null;
  }

  const reportedFields = group.fields.filter((def) => isReported(details, def));
  if (reportedFields.length === 0) {
    return (
      <p className="border-t border-border px-5 py-6 text-small text-text-muted">
        No reported fields in this section.
      </p>
    );
  }

  return (
    <dl className="grid gap-3 border-t border-border px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
      {reportedFields.map((def) => {
        const rawValue = details[def.name];
        if (rawValue === undefined || rawValue === null) {
          return null;
        }

        return (
          <div
            key={def.name}
            className="rounded-md border border-border bg-surface p-4"
          >
            <dt className="text-caption font-semibold uppercase text-text-muted">
              {labelFor(def.name)}
            </dt>
            <dd className={valueClassName(def.emphasis)}>
              {formatIncidentFieldValue(def, rawValue)}
            </dd>
          </div>
        );
      })}
    </dl>
  );
};
