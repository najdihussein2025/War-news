import { labelFor } from "../fieldLabels";
import { formatIncidentFieldValue } from "../formatIncidentFieldValue";
import type { IncidentCategorySectionKey } from "../incidentCategorySections";
import { fieldGroupForSection } from "../incidentCategorySections";
import { initialFormDetails, isRollupField } from "../incidentEditHelpers";
import type { IncidentDetails } from "../incidentSchema";
import { isReported } from "../incidentSchema";

type Props = {
  sectionKey: IncidentCategorySectionKey;
  details: IncidentDetails | null;
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

  const isEmptySection = details === null;
  const seededDetails = initialFormDetails(group, details);
  const displayFields = isEmptySection
    ? group.fields.filter((def) => !isRollupField(def.name))
    : group.fields.filter((def) => isReported(details, def));
  const rollupFields = isEmptySection
    ? group.fields.filter((def) => isRollupField(def.name))
    : [];
  const formatEmptyValue = (name: string) => {
    const rawValue = seededDetails[name];
    if (rawValue === "") {
      return "\u2014";
    }
    return String(rawValue);
  };

  if (displayFields.length === 0 && rollupFields.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4 border-t border-border px-5 py-4">
      {isEmptySection ? (
        <p className="rounded-md bg-surface-muted px-3 py-2 text-small text-text-muted">
          This section has no recorded data yet. The full field structure is shown below.
        </p>
      ) : null}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {displayFields.map((def) => {
          const rawValue = isEmptySection ? seededDetails[def.name] : details[def.name];
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
                {isEmptySection
                  ? formatEmptyValue(def.name)
                  : formatIncidentFieldValue(def, rawValue)}
              </dd>
            </div>
          );
        })}
      </dl>

      {rollupFields.length > 0 ? (
        <div className="rounded-md bg-surface-muted p-3">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Computed fields (read-only)
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {rollupFields.map((def) => (
              <div key={def.name}>
                <p className="text-caption text-text-muted">{labelFor(def.name)}</p>
                <p className={valueClassName(def.emphasis)}>{formatEmptyValue(def.name)}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};
