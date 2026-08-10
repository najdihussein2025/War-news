// Human-readable labels for incident_details columns.
// Hardcoded for the mock frontend; shaped as {field_name, label_en} pairs so it
// can be swapped for the field_definitions table (db.md §7) once wired to real data.

export type FieldLabel = {
  field_name: string;
  label_en: string;
};

export const fieldLabels: FieldLabel[] = [
  // Casualty demographics
  { field_name: "male_d", label_en: "Male — Deaths" },
  { field_name: "male_i", label_en: "Male — Injuries" },
  { field_name: "female_d", label_en: "Female — Deaths" },
  { field_name: "female_i", label_en: "Female — Injuries" },
  { field_name: "child_d", label_en: "Children — Deaths" },
  { field_name: "child_i", label_en: "Children — Injuries" },
  { field_name: "obs_duties", label_en: "Hit during observation duties" },
  { field_name: "isf_gs", label_en: "ISF / General Security affected" },
  { field_name: "fire", label_en: "Fire broke out" },
  { field_name: "arrested", label_en: "Persons arrested" },
  { field_name: "lib_y_n", label_en: "Lebanese national (Y/N)" },
  { field_name: "total_deaths", label_en: "Total deaths" },
  { field_name: "total_injuries", label_en: "Total injuries" },

  // Lebanese Army (LA)
  { field_name: "la", label_en: "Lebanese Army involved" },
  { field_name: "la_did", label_en: "LA damage assessment" },
  { field_name: "la_bldg", label_en: "LA buildings hit" },
  { field_name: "la_v", label_en: "LA vehicles hit" },
  { field_name: "lam_d", label_en: "LA Male — Deaths" },
  { field_name: "lam_i", label_en: "LA Male — Injuries" },
  { field_name: "laf_d", label_en: "LA Female — Deaths" },
  { field_name: "laf_i", label_en: "LA Female — Injuries" },
  { field_name: "la_td", label_en: "LA total deaths" },
  { field_name: "la_ti", label_en: "LA total injuries" },

  // UNIFIL
  { field_name: "unifil", label_en: "UNIFIL involved" },
  { field_name: "un_did", label_en: "UNIFIL damage assessment" },
  { field_name: "un_bldg", label_en: "UNIFIL buildings hit" },
  { field_name: "un_v", label_en: "UNIFIL vehicles hit" },
  { field_name: "unm_d", label_en: "UNIFIL Male — Deaths" },
  { field_name: "unm_i", label_en: "UNIFIL Male — Injuries" },
  { field_name: "unf_d", label_en: "UNIFIL Female — Deaths" },
  { field_name: "unf_i", label_en: "UNIFIL Female — Injuries" },
  { field_name: "un_td", label_en: "UNIFIL total deaths" },
  { field_name: "un_ti", label_en: "UNIFIL total injuries" },

  // Municipality
  { field_name: "muni", label_en: "Municipality affected" },
  { field_name: "muni_did", label_en: "Municipality damage assessment" },
  { field_name: "muni_bldg", label_en: "Municipal buildings hit" },
  { field_name: "muni_empl", label_en: "Municipal employees affected" },
  { field_name: "muni_m_d", label_en: "Municipality Male — Deaths" },
  { field_name: "muni_m_i", label_en: "Municipality Male — Injuries" },
  { field_name: "muni_f_d", label_en: "Municipality Female — Deaths" },
  { field_name: "muni_f_i", label_en: "Municipality Female — Injuries" },
  { field_name: "muni_td", label_en: "Municipality total deaths" },
  { field_name: "muni_ti", label_en: "Municipality total injuries" },

  // School / University
  { field_name: "school", label_en: "School hit" },
  { field_name: "sch_did", label_en: "School damage assessment" },
  { field_name: "school_name", label_en: "School name" },
  { field_name: "sch_damage_level", label_en: "School damage level" },
  { field_name: "uni", label_en: "University hit" },
  { field_name: "uni_did", label_en: "University damage assessment" },
  { field_name: "uni_name", label_en: "University name" },

  // Religious & cultural
  { field_name: "church", label_en: "Church hit" },
  { field_name: "chu_did", label_en: "Church damage assessment" },
  { field_name: "chu_n", label_en: "Church name" },
  { field_name: "mosque", label_en: "Mosque hit" },
  { field_name: "mos_did", label_en: "Mosque damage assessment" },
  { field_name: "mosque_n", label_en: "Mosque name" },
  { field_name: "ceme", label_en: "Cemetery hit" },
  { field_name: "ceme_did", label_en: "Cemetery damage assessment" },
  { field_name: "ceme_n", label_en: "Cemetery name" },
  { field_name: "releg", label_en: "Religious site hit" },
  { field_name: "releg_did", label_en: "Religious site damage assessment" },
  { field_name: "releg_n", label_en: "Religious site name" },
  { field_name: "archeo", label_en: "Archaeological site hit" },
  { field_name: "arch_did", label_en: "Archaeological damage assessment" },
  { field_name: "arch_n", label_en: "Archaeological site name" },

  // Hospital
  { field_name: "hosp", label_en: "Hospital hit" },
  { field_name: "hos_did", label_en: "Hospital damage assessment" },
  { field_name: "hos_status", label_en: "Hospital status" },
  { field_name: "hos_n", label_en: "Hospital name" },
  { field_name: "hos_damage_level", label_en: "Hospital damage level" },
  { field_name: "nbr_evap", label_en: "Patients evacuated" },
  { field_name: "hos_m_d", label_en: "Hospital Male — Deaths" },
  { field_name: "hos_m_i", label_en: "Hospital Male — Injuries" },
  { field_name: "hos_f_d", label_en: "Hospital Female — Deaths" },
  { field_name: "hos_f_i", label_en: "Hospital Female — Injuries" },

  // Health center
  { field_name: "hc", label_en: "Health center hit" },
  { field_name: "hc_rela", label_en: "Health center affiliation" },
  { field_name: "hc_did", label_en: "Health center damage assessment" },
  { field_name: "hc_damage_level", label_en: "Health center damage level" },
  { field_name: "hc_m_d", label_en: "Health Center Male — Deaths" },
  { field_name: "hc_m_i", label_en: "Health Center Male — Injuries" },
  { field_name: "hc_f_d", label_en: "Health Center Female — Deaths" },
  { field_name: "hc_f_i", label_en: "Health Center Female — Injuries" },

  // Emergency / Civil Defense
  { field_name: "emer", label_en: "Emergency / Civil Defense involved" },
  { field_name: "e_cars", label_en: "Emergency vehicles hit" },
  { field_name: "car_nbr", label_en: "Vehicle number / plate" },
  { field_name: "emer_rela", label_en: "Emergency team affiliation" },
  { field_name: "emer_d", label_en: "Emergency crew — Deaths" },
  { field_name: "emer_i", label_en: "Emergency crew — Injuries" },

  // Press
  { field_name: "press", label_en: "Press affected" },
  { field_name: "channel", label_en: "Channel / outlet" },
  { field_name: "press_did", label_en: "Press damage assessment" },
  { field_name: "press_m_d", label_en: "Press Male — Deaths" },
  { field_name: "press_m_i", label_en: "Press Male — Injuries" },
  { field_name: "press_f_d", label_en: "Press Female — Deaths" },
  { field_name: "press_f_i", label_en: "Press Female — Injuries" },

  // Government building
  { field_name: "gov", label_en: "Government building hit" },
  { field_name: "gov_bui", label_en: "Government buildings count" },
  { field_name: "gov_n", label_en: "Government building name" },
  { field_name: "gb_did", label_en: "Government building damage assessment" },
  { field_name: "gb_m_d", label_en: "Government Building Male — Deaths" },
  { field_name: "gb_m_i", label_en: "Government Building Male — Injuries" },
  { field_name: "gb_f_d", label_en: "Government Building Female — Deaths" },
  { field_name: "gb_f_i", label_en: "Government Building Female — Injuries" },

  // Road / Bridge
  { field_name: "road", label_en: "Road hit" },
  { field_name: "road_d_id", label_en: "Road damage assessment" },
  { field_name: "road_blocked", label_en: "Road blocked" },
  { field_name: "road_name", label_en: "Road name" },
  { field_name: "bridge", label_en: "Bridge hit" },
  { field_name: "bridge_blocked", label_en: "Bridge blocked" },
  { field_name: "bridge_name", label_en: "Bridge name" },

  // Vehicles
  { field_name: "car", label_en: "Civilian cars hit" },
  { field_name: "car_d", label_en: "Car occupants — Deaths" },
  { field_name: "car_i", label_en: "Car occupants — Injuries" },
  { field_name: "car_m_d", label_en: "Car Male — Deaths" },
  { field_name: "car_m_i", label_en: "Car Male — Injuries" },
  { field_name: "car_f_d", label_en: "Car Female — Deaths" },
  { field_name: "car_f_i", label_en: "Car Female — Injuries" },
  { field_name: "car_c_d", label_en: "Car Children — Deaths" },
  { field_name: "car_c_i", label_en: "Car Children — Injuries" },
  { field_name: "moto", label_en: "Motorcycles hit" },
  { field_name: "moto_did", label_en: "Motorcycle damage assessment" },
  { field_name: "moto_d", label_en: "Motorcycle — Deaths" },
  { field_name: "moto_i", label_en: "Motorcycle — Injuries" },
  { field_name: "con_veh", label_en: "Construction vehicles hit" },
  { field_name: "con_d", label_en: "Construction crew — Deaths" },
  { field_name: "con_i", label_en: "Construction crew — Injuries" },
  { field_name: "excavator", label_en: "Excavators" },
  { field_name: "bulldozer", label_en: "Bulldozers" },
  { field_name: "camion", label_en: "Trucks (camion)" },
  { field_name: "bobcat", label_en: "Bobcats" },
  { field_name: "tracteur", label_en: "Tractors" },
  { field_name: "total_con", label_en: "Total construction vehicles" },

  // Crossings & other
  { field_name: "crossing", label_en: "Border crossing affected" },
  { field_name: "litani", label_en: "Litani crossing" },
  { field_name: "zahrani", label_en: "Zahrani crossing" },
  { field_name: "drone_f", label_en: "Drone overflight" },
  { field_name: "water", label_en: "Water infrastructure hit" },
  { field_name: "water_did", label_en: "Water damage assessment" },
  { field_name: "water_type", label_en: "Water infrastructure type" },
  { field_name: "electric", label_en: "Electric infrastructure hit" },
  { field_name: "electric_did", label_en: "Electric damage assessment" },
  { field_name: "electric_type", label_en: "Electric infrastructure type" },
  { field_name: "olives_trees_d", label_en: "Olive trees damaged" },
  { field_name: "mjnoub", label_en: "MJnoub affected" },
  { field_name: "mj_did", label_en: "MJnoub damage assessment" },
  { field_name: "other", label_en: "Other site affected" },
  { field_name: "other_did", label_en: "Other damage assessment" },
  { field_name: "other_type", label_en: "Other site type" },
  { field_name: "other_d", label_en: "Other — Deaths" },
  { field_name: "other_i", label_en: "Other — Injuries" },

  // Warning & classification
  { field_name: "no_warning", label_en: "No warning given" },
  { field_name: "warning", label_en: "Warning given" },
  { field_name: "genocide", label_en: "Genocide classification" },
  { field_name: "building", label_en: "Buildings destroyed" },
  { field_name: "apart", label_en: "Apartments damaged" },

  // Record information
  { field_name: "moh", label_en: "MoH cross-checked" },
  { field_name: "worker_name", label_en: "Data worker" },
  { field_name: "source_link", label_en: "Source link" },
  { field_name: "source_link_2", label_en: "Source link 2" },
  { field_name: "martyrs", label_en: "Martyrs (names)" },
  { field_name: "note", label_en: "Note" },
];

const labelMap = new Map(fieldLabels.map((item) => [item.field_name, item.label_en]));

export const labelFor = (fieldName: string) => labelMap.get(fieldName) ?? fieldName;
