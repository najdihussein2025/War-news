import type { FieldGroup } from "./incidentSchema";
import { incidentFieldGroups } from "./incidentSchema";

export type IncidentCategorySectionKey =
  | "lebanese_army"
  | "unifil"
  | "municipality"
  | "school_university"
  | "religious_cultural"
  | "hospital"
  | "health_center"
  | "emergency_civil_defense"
  | "press"
  | "government_building"
  | "road_bridge"
  | "vehicles"
  | "crossings_other"
  | "warning_classification";

export type IncidentCategorySection = Record<string, number | string>;

const SECTION_GROUP_NAMES: Record<IncidentCategorySectionKey, string> = {
  lebanese_army: "Lebanese Army (LA)",
  unifil: "UNIFIL",
  municipality: "Municipality",
  school_university: "School / University",
  religious_cultural: "Religious & cultural",
  hospital: "Hospital",
  health_center: "Health Center",
  emergency_civil_defense: "Emergency / Civil Defense",
  press: "Press",
  government_building: "Government building",
  road_bridge: "Road / Bridge",
  vehicles: "Vehicles",
  crossings_other: "Crossings & other",
  warning_classification: "Warning & classification",
};

export const incidentCategorySections: Array<{
  key: IncidentCategorySectionKey;
  label: string;
}> = (
  Object.entries(SECTION_GROUP_NAMES) as Array<[IncidentCategorySectionKey, string]>
).map(([key, label]) => ({ key, label }));

export const fieldGroupForSection = (
  sectionKey: IncidentCategorySectionKey,
): FieldGroup | undefined =>
  incidentFieldGroups.find(
    (group) => group.name === SECTION_GROUP_NAMES[sectionKey],
  );
