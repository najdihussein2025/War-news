import { useState } from "react";
import { isAxiosError } from "axios";
import { Button, Input, Label } from "../../../components/ui";
import { labelFor } from "../fieldLabels";
import { formatIncidentFieldValue } from "../formatIncidentFieldValue";
import type { IncidentCategorySectionKey } from "../incidentCategorySections";
import { fieldGroupForSection } from "../incidentCategorySections";
import {
  applyGateOff,
  changedFields,
  initialFormDetails,
  isFieldEditable,
  isRollupField,
  validateSectionForm,
} from "../incidentEditHelpers";
import type { FieldDef, IncidentDetails } from "../incidentSchema";

type Props = {
  sectionKey: IncidentCategorySectionKey;
  details: IncidentDetails | null;
  onSave: (fields: IncidentDetails) => Promise<void>;
  onCancel: () => void;
};

const RollupHint = ({ def, details }: { def: FieldDef; details: IncidentDetails }) => {
  const value = details[def.name];
  if (value === undefined || value === null || Number(value) === 0) {
    return null;
  }
  return (
    <p className="mt-1 text-caption text-text-muted">
      Computed: {formatIncidentFieldValue(def, value)}
    </p>
  );
};

const FieldInput = ({
  def,
  details,
  disabled,
  onChange,
}: {
  def: FieldDef;
  details: IncidentDetails;
  disabled: boolean;
  onChange: (name: string, value: number | string) => void;
}) => {
  const value = details[def.name] ?? "";

  if (def.kind === "flag") {
    return (
      <select
        id={`edit-${def.name}`}
        className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-body"
        disabled={disabled}
        value={Number(value) > 0 ? "1" : "0"}
        onChange={(event) => onChange(def.name, Number(event.target.value))}
      >
        <option value="0">No</option>
        <option value="1">Yes</option>
      </select>
    );
  }

  if (def.kind === "did") {
    return (
      <select
        id={`edit-${def.name}`}
        className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-body"
        disabled={disabled}
        value={String(value)}
        onChange={(event) => onChange(def.name, event.target.value)}
      >
        <option value="">Select…</option>
        <option value="D">Direct</option>
        <option value="ID">Indirect</option>
      </select>
    );
  }

  if (def.kind === "count") {
    return (
      <Input
        id={`edit-${def.name}`}
        type="number"
        min={0}
        disabled={disabled}
        value={value === "" ? "" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(def.name, raw === "" ? 0 : Number(raw));
        }}
      />
    );
  }

  return (
    <Input
      id={`edit-${def.name}`}
      disabled={disabled}
      value={String(value)}
      onChange={(event) => onChange(def.name, event.target.value)}
    />
  );
};

export const IncidentCategorySectionEditForm = ({
  sectionKey,
  details,
  onSave,
  onCancel,
}: Props) => {
  const group = fieldGroupForSection(sectionKey);
  const [formDetails, setFormDetails] = useState<IncidentDetails>(() =>
    initialFormDetails(group!, details),
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  if (!group) {
    return null;
  }

  const editableFields = group.fields.filter((def) => !isRollupField(def.name));
  const rollupFields = group.fields.filter((def) => isRollupField(def.name));
  const baseline = initialFormDetails(group, details);
  const isEmptySection = details === null;

  const handleChange = (name: string, value: number | string) => {
    setError("");
    setFormDetails((current) => {
      const def = group.fields.find((field) => field.name === name);
      let next = { ...current, [name]: value };
      if (def?.kind === "flag" && Number(value) === 0) {
        next = applyGateOff(next, group, name);
      }
      return next;
    });
  };

  return (
    <form
      className="space-y-4 border-t border-border px-5 py-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const validationError = validateSectionForm(group, formDetails);
        if (validationError) {
          setError(validationError);
          return;
        }
        const diff = changedFields(baseline, formDetails);
        if (Object.keys(diff).length === 0) {
          onCancel();
          return;
        }
        setIsSaving(true);
        setError("");
        try {
          await onSave(diff);
        } catch (caught) {
          if (isAxiosError(caught) && typeof caught.response?.data?.detail === "string") {
            setError(caught.response.data.detail);
          } else {
            setError("Could not save changes. Please check the values and try again.");
          }
        } finally {
          setIsSaving(false);
        }
      }}
    >
      {isEmptySection ? (
        <p className="rounded-md bg-surface-muted px-3 py-2 text-small text-text-muted">
          This section has no recorded data yet. Set the gate flag to Yes and fill in
          the fields below to add it.
        </p>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {editableFields.map((def) => {
          const disabled = !isFieldEditable(group, formDetails, def);
          return (
            <div key={def.name} className="rounded-md border border-border bg-surface p-4">
              <Label htmlFor={`edit-${def.name}`}>{labelFor(def.name)}</Label>
              <FieldInput
                def={def}
                details={formDetails}
                disabled={disabled}
                onChange={handleChange}
              />
              {disabled && def.kind === "did" ? (
                <p className="mt-1 text-caption text-text-muted">
                  Locked until the controlling flag is set.
                </p>
              ) : null}
            </div>
          );
        })}
      </div>

      {rollupFields.length > 0 ? (
        <div className="rounded-md bg-surface-muted p-3">
          <p className="text-caption font-semibold uppercase text-text-muted">
            Computed fields (read-only)
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {rollupFields.map((def) => (
              <div key={def.name}>
                <p className="text-caption text-text-muted">{labelFor(def.name)}</p>
                <RollupHint def={def} details={details ?? formDetails} />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {error ? <p className="text-small text-danger">{error}</p> : null}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" disabled={isSaving} onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSaving} loadingText="Saving">
          Save section
        </Button>
      </div>
    </form>
  );
};
