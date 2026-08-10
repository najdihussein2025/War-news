// Grouped incident_details schema mirroring db.md's 14+1 category grouping.
// Every *_did field names its controlling flag via `controlledBy`: when the flag
// is 0 the assessment is locked (not merely missing); when 1 it holds D or ID.

export type FieldKind = "flag" | "count" | "did" | "text";

export type FieldDef = {
  name: string;
  kind: FieldKind;
  controlledBy?: string;
  emphasis?: "deaths" | "injuries";
};

export type FieldGroup = {
  name: string;
  fields: FieldDef[];
};

const flag = (name: string): FieldDef => ({ name, kind: "flag" });
const count = (name: string): FieldDef => ({ name, kind: "count" });
const text = (name: string): FieldDef => ({ name, kind: "text" });
const did = (name: string, controlledBy: string): FieldDef => ({ name, kind: "did", controlledBy });
const deaths = (name: string): FieldDef => ({ name, kind: "count", emphasis: "deaths" });
const injuries = (name: string): FieldDef => ({ name, kind: "count", emphasis: "injuries" });

export const incidentFieldGroups: FieldGroup[] = [
  {
    name: "Casualty demographics",
    fields: [
      deaths("male_d"), injuries("male_i"),
      deaths("female_d"), injuries("female_i"),
      deaths("child_d"), injuries("child_i"),
      flag("obs_duties"), flag("isf_gs"), flag("fire"),
      count("arrested"), flag("lib_y_n"),
      deaths("total_deaths"), injuries("total_injuries"),
    ],
  },
  {
    name: "Lebanese Army (LA)",
    fields: [
      flag("la"), did("la_did", "la"),
      count("la_bldg"), count("la_v"),
      deaths("lam_d"), injuries("lam_i"),
      deaths("laf_d"), injuries("laf_i"),
      deaths("la_td"), injuries("la_ti"),
    ],
  },
  {
    name: "UNIFIL",
    fields: [
      flag("unifil"), did("un_did", "unifil"),
      count("un_bldg"), count("un_v"),
      deaths("unm_d"), injuries("unm_i"),
      deaths("unf_d"), injuries("unf_i"),
      deaths("un_td"), injuries("un_ti"),
    ],
  },
  {
    name: "Municipality",
    fields: [
      flag("muni"), did("muni_did", "muni"),
      count("muni_bldg"), count("muni_empl"),
      deaths("muni_m_d"), injuries("muni_m_i"),
      deaths("muni_f_d"), injuries("muni_f_i"),
      deaths("muni_td"), injuries("muni_ti"),
    ],
  },
  {
    name: "School / University",
    fields: [
      flag("school"), did("sch_did", "school"),
      text("school_name"), text("sch_damage_level"),
      flag("uni"), did("uni_did", "uni"), text("uni_name"),
    ],
  },
  {
    name: "Religious & cultural",
    fields: [
      flag("church"), did("chu_did", "church"), text("chu_n"),
      flag("mosque"), did("mos_did", "mosque"), text("mosque_n"),
      flag("ceme"), did("ceme_did", "ceme"), text("ceme_n"),
      flag("releg"), did("releg_did", "releg"), text("releg_n"),
      flag("archeo"), did("arch_did", "archeo"), text("arch_n"),
    ],
  },
  {
    name: "Hospital",
    fields: [
      flag("hosp"), did("hos_did", "hosp"),
      text("hos_status"), text("hos_n"), text("hos_damage_level"),
      count("nbr_evap"),
      deaths("hos_m_d"), injuries("hos_m_i"),
      deaths("hos_f_d"), injuries("hos_f_i"),
    ],
  },
  {
    name: "Health Center",
    fields: [
      flag("hc"), text("hc_rela"), did("hc_did", "hc"), text("hc_damage_level"),
      deaths("hc_m_d"), injuries("hc_m_i"),
      deaths("hc_f_d"), injuries("hc_f_i"),
    ],
  },
  {
    name: "Emergency / Civil Defense",
    fields: [
      flag("emer"), count("e_cars"), text("car_nbr"), text("emer_rela"),
      deaths("emer_d"), injuries("emer_i"),
    ],
  },
  {
    name: "Press",
    fields: [
      flag("press"), text("channel"), did("press_did", "press"),
      deaths("press_m_d"), injuries("press_m_i"),
      deaths("press_f_d"), injuries("press_f_i"),
    ],
  },
  {
    name: "Government building",
    fields: [
      flag("gov"), count("gov_bui"), text("gov_n"), did("gb_did", "gov"),
      deaths("gb_m_d"), injuries("gb_m_i"),
      deaths("gb_f_d"), injuries("gb_f_i"),
    ],
  },
  {
    name: "Road / Bridge",
    fields: [
      flag("road"), did("road_d_id", "road"), flag("road_blocked"), text("road_name"),
      flag("bridge"), flag("bridge_blocked"), text("bridge_name"),
    ],
  },
  {
    name: "Vehicles",
    fields: [
      count("car"), deaths("car_d"), injuries("car_i"),
      deaths("car_m_d"), injuries("car_m_i"),
      deaths("car_f_d"), injuries("car_f_i"),
      deaths("car_c_d"), injuries("car_c_i"),
      count("moto"), did("moto_did", "moto"),
      deaths("moto_d"), injuries("moto_i"),
      count("con_veh"), deaths("con_d"), injuries("con_i"),
      count("excavator"), count("bulldozer"), count("camion"),
      count("bobcat"), count("tracteur"), count("total_con"),
    ],
  },
  {
    name: "Crossings & other",
    fields: [
      flag("crossing"), flag("litani"), flag("zahrani"), flag("drone_f"),
      flag("water"), did("water_did", "water"), text("water_type"),
      flag("electric"), did("electric_did", "electric"), text("electric_type"),
      count("olives_trees_d"),
      flag("mjnoub"), did("mj_did", "mjnoub"),
      flag("other"), did("other_did", "other"), text("other_type"),
      deaths("other_d"), injuries("other_i"),
    ],
  },
  {
    name: "Warning & classification",
    fields: [
      flag("no_warning"), flag("warning"), flag("genocide"),
      count("building"), count("apart"),
    ],
  },
];

// moh, worker_name, source_link, source_link_2, martyrs — shown in the record
// header rather than a collapsible group.
export const recordInfoFields: FieldDef[] = [
  flag("moh"),
  text("worker_name"),
  text("source_link"),
  text("source_link_2"),
  text("martyrs"),
];

export type IncidentDetails = Record<string, number | string>;

export const fieldValue = (details: IncidentDetails, def: FieldDef) => details[def.name];

// A field counts as "reported" when it carries real data: DID fields only when
// their controlling flag is set, numerics when non-zero, text when non-empty.
export const isReported = (details: IncidentDetails, def: FieldDef): boolean => {
  if (def.kind === "did") {
    return Number(details[def.controlledBy!] ?? 0) === 1;
  }
  const value = details[def.name];
  if (def.kind === "text") {
    return typeof value === "string" && value.trim() !== "";
  }
  return Number(value ?? 0) > 0;
};

export const reportedCount = (details: IncidentDetails, group: FieldGroup) =>
  group.fields.filter((def) => isReported(details, def)).length;
