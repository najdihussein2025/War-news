import type { FieldDef } from "./incidentSchema";

export const formatIncidentFieldValue = (
  def: FieldDef,
  value: number | string,
): string => {
  if (def.kind === "did") {
    if (value === "D") {
      return "Direct";
    }
    if (value === "ID") {
      return "Indirect";
    }
    return String(value);
  }

  if (def.kind === "flag") {
    return Number(value) > 0 ? "Yes" : "No";
  }

  return String(value);
};
