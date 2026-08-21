import type { FieldDef, FieldGroup, IncidentDetails } from "./incidentSchema";

export type GateSubgroup = {
  gate: string;
  fields: FieldDef[];
};

/** Split a category field group into gate-controlled subgroups. */
export const gateSubgroups = (group: FieldGroup): GateSubgroup[] => {
  const gateNames = new Set<string>();
  for (const field of group.fields) {
    if (field.kind === "flag") {
      gateNames.add(field.name);
    }
    if (field.controlledBy) {
      gateNames.add(field.controlledBy);
    }
  }

  const subgroups: GateSubgroup[] = [];
  let current: GateSubgroup | null = null;

  for (const field of group.fields) {
    if (field.kind === "flag" && gateNames.has(field.name)) {
      current = { gate: field.name, fields: [field] };
      subgroups.push(current);
      continue;
    }
    if (current) {
      current.fields.push(field);
    }
  }

  return subgroups;
};

export const isGateActive = (details: IncidentDetails, gate: string) =>
  Number(details[gate] ?? 0) === 1;

export const emptyValueForField = (def: FieldDef): number | string => {
  if (def.kind === "text") {
    return "";
  }
  return 0;
};

export const isRollupField = (name: string) =>
  name.endsWith("_td") ||
  name.endsWith("_ti") ||
  name === "car_d" ||
  name === "car_i" ||
  name === "total_con";

const DID_READY_VALUES = new Set(["D", "ID"]);
const CLEAN_CHAIN_GATES = new Set([
  "la",
  "unifil",
  "muni",
  "hosp",
  "hc",
  "water",
  "electric",
  "mjnoub",
  "other",
]);

const cleanChainDidField = (group: FieldGroup, def: FieldDef) => {
  const subgroup = gateSubgroups(group).find((entry) =>
    entry.fields.some((field) => field.name === def.name),
  );
  if (!subgroup || !CLEAN_CHAIN_GATES.has(subgroup.gate)) {
    return null;
  }

  const didField = subgroup.fields.find((field) => field.kind === "did");
  if (!didField || didField.controlledBy !== subgroup.gate) {
    return null;
  }

  const firstField = subgroup.fields[0];
  if (!firstField || firstField.kind !== "flag" || firstField.name !== subgroup.gate) {
    return null;
  }

  return didField;
};

/** When a gate is turned off, clear its dependent fields in form state. */
export const applyGateOff = (
  details: IncidentDetails,
  group: FieldGroup,
  gate: string,
): IncidentDetails => {
  const subgroup = gateSubgroups(group).find((entry) => entry.gate === gate);
  if (!subgroup) {
    return details;
  }

  const next = { ...details, [gate]: 0 };
  for (const field of subgroup.fields) {
    if (field.name === gate) {
      continue;
    }
    next[field.name] = emptyValueForField(field);
  }
  return next;
};

export const isFieldEditable = (
  group: FieldGroup,
  details: IncidentDetails,
  def: FieldDef,
): boolean => {
  if (def.kind === "did") {
    return isGateActive(details, def.controlledBy!);
  }

  const didField = cleanChainDidField(group, def);
  if (!didField || def.name === didField.name) {
    return true;
  }

  const subgroup = gateSubgroups(group).find((entry) =>
    entry.fields.some((field) => field.name === def.name),
  );
  if (!subgroup) {
    return true;
  }

  const didIndex = subgroup.fields.findIndex((field) => field.name === didField.name);
  const fieldIndex = subgroup.fields.findIndex((field) => field.name === def.name);
  if (fieldIndex <= didIndex) {
    return true;
  }

  return DID_READY_VALUES.has(String(details[didField.name] ?? ""));
};

/** Seed edit form from API section payload or blank defaults for empty sections. */
export const initialFormDetails = (
  group: FieldGroup,
  details: IncidentDetails | null,
): IncidentDetails => {
  const base: IncidentDetails = {};
  for (const field of group.fields) {
    if (isRollupField(field.name)) {
      continue;
    }
    const existing = details?.[field.name];
    if (existing !== undefined && existing !== null) {
      base[field.name] = existing;
    } else {
      base[field.name] = emptyValueForField(field);
    }
  }
  return base;
};

export const validateSectionForm = (
  group: FieldGroup,
  details: IncidentDetails,
): string | null => {
  for (const subgroup of gateSubgroups(group)) {
    if (!isGateActive(details, subgroup.gate)) {
      continue;
    }
    const didField = subgroup.fields.find((field) => field.kind === "did");
    if (!didField) {
      continue;
    }
    const value = details[didField.name];
    if (value !== "D" && value !== "ID") {
      return `${subgroup.gate} damage type is required when marked present (D or ID).`;
    }
  }
  return null;
};

export const changedFields = (
  before: IncidentDetails,
  after: IncidentDetails,
): IncidentDetails => {
  const diff: IncidentDetails = {};
  for (const [key, value] of Object.entries(after)) {
    if (before[key] !== value) {
      diff[key] = value;
    }
  }
  return diff;
};
