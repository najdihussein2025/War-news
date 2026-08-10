import type { IncidentDetails } from "../features/news/incidentSchema";

// Sparse per-incident detail records keyed by incident id. Missing keys mean
// 0 / not reported, matching how the real incident_details rows behave — most
// of the 191 columns are empty for any given incident.
export const mockIncidentDetails: Record<string, IncidentDetails> = {
  // Shelling impact near residential edge — casualties, municipality, vehicles, olives.
  inc_001: {
    male_d: 1, male_i: 2, female_i: 1, total_deaths: 1, total_injuries: 3, lib_y_n: 1,
    muni: 1, muni_did: "D", muni_bldg: 1,
    car: 1, car_i: 1, car_m_i: 1,
    olives_trees_d: 40,
    no_warning: 1, building: 1,
    moh: 1, worker_name: "Rana Fakih",
    source_link: "https://t.me/s/southlebnews/842199",
    martyrs: "Hassan K. (48)",
    note: "Cross-checked with municipality duty officer; MoH tally pending.",
  },

  // Dense record: early-morning airstrike with structural damage — used to
  // exercise density across many populated groups at once.
  inc_002: {
    male_d: 2, male_i: 3, female_d: 1, female_i: 2, child_i: 1,
    total_deaths: 3, total_injuries: 6, fire: 1, lib_y_n: 1,
    school: 1, sch_did: "ID", school_name: "Khiam Intermediate School", sch_damage_level: "Minor",
    uni: 1, uni_did: "ID", uni_name: "Khiam Technical Institute",
    hosp: 1, hos_did: "D", hos_status: "Partially operating", hos_n: "Khiam Governmental Hospital",
    hos_damage_level: "Partial", nbr_evap: 12, hos_f_i: 1,
    emer: 1, e_cars: 2, car_nbr: "CD-114", emer_rela: "Civil Defense Khiam", emer_i: 1,
    road: 1, road_d_id: "D", road_blocked: 1, road_name: "Khiam – Marjayoun road",
    car: 2, car_d: 1, car_i: 2, car_m_d: 1, car_m_i: 1, car_f_i: 1,
    con_veh: 1, excavator: 1, total_con: 1,
    water: 1, water_did: "ID", water_type: "Main supply line",
    electric: 1, electric_did: "D", electric_type: "Low-voltage grid",
    no_warning: 1, building: 2, apart: 4,
    moh: 1, worker_name: "Rana Fakih",
    source_link: "https://cnrs.example/api/reports/2026-08-10/09",
    source_link_2: "https://t.me/s/southlebnews/842203",
    martyrs: "Ahmad S. (34), Mahmoud R. (29), Zeinab T. (61)",
    note: "Two adjacent homes destroyed; hospital annex caught fragment damage. Names confirmed by family sources.",
  },

  // Sparse record: drone overflight, no impact — used to exercise the
  // all-collapsed empty-state defaults.
  inc_003: {
    drone_f: 1,
    worker_name: "Omar Srour",
    source_link: "https://ops.example/manual/ops-118",
    note: "Observation-only entry. No damage or casualties reported.",
  },

  // Shell fragments reached a roadside shop — injuries, press, health center.
  inc_004: {
    male_i: 2, total_injuries: 2,
    hc: 1, hc_rela: "Islamic Health Committee", hc_did: "ID", hc_damage_level: "Minor", hc_m_i: 1,
    emer: 1, e_cars: 1, emer_rela: "Red Cross Bint Jbeil",
    press: 1, channel: "Al Manar", press_did: "D", press_m_i: 1,
    warning: 1,
    moh: 1, worker_name: "Omar Srour",
    source_link: "https://t.me/s/southlebnews/842011",
  },

  // Naval fire near coastal farmland — LA and UNIFIL presence.
  inc_005: {
    la: 1, la_did: "ID", la_v: 1,
    unifil: 1, un_did: "ID", un_v: 1, unm_i: 1, un_ti: 1,
    olives_trees_d: 15,
    worker_name: "Rana Fakih",
    source_link: "https://cnrs.example/api/reports/2026-08-09/22",
    note: "UNIFIL patrol vehicle reported light damage; awaiting official confirmation.",
  },

  // Displacement after repeated impacts — municipality, school, mosque, housing.
  inc_006: {
    muni: 1, muni_did: "ID", muni_empl: 4,
    school: 1, sch_did: "D", school_name: "Taybeh Public School", sch_damage_level: "Minor",
    mosque: 1, mos_did: "ID", mosque_n: "Taybeh Grand Mosque",
    gov: 1, gov_bui: 1, gov_n: "Municipal warehouse", gb_did: "ID",
    mjnoub: 1, mj_did: "ID",
    building: 3, apart: 6, warning: 1,
    worker_name: "Omar Srour",
    source_link: "https://t.me/s/southlebnews/841772",
    note: "Roughly 20 families relocated to Marjayoun overnight.",
  },

  // Targeted strike on infrastructure — water, electric, road, gov building.
  inc_007: {
    gov: 1, gov_bui: 1, gov_n: "Yaroun municipal office", gb_did: "D",
    road: 1, road_d_id: "ID", road_name: "Yaroun eastern approach",
    water: 1, water_did: "D", water_type: "Reservoir feed line",
    electric: 1, electric_did: "D", electric_type: "Village transformer",
    no_warning: 1,
    worker_name: "Rana Fakih",
    source_link: "https://ops.example/manual/ops-103",
  },

  // Vehicle struck near hospital road — casualty, hospital, health center, press.
  inc_008: {
    male_d: 1, total_deaths: 1,
    hosp: 1, hos_did: "ID", hos_status: "Operational", hos_n: "Mays al-Jabal Governmental Hospital", hos_damage_level: "Minor",
    hc: 1, hc_rela: "Amel Association", hc_did: "ID", hc_m_i: 1,
    press: 1, channel: "Reuters stringer", press_did: "ID",
    car: 1, car_d: 1, car_m_d: 1,
    no_warning: 1,
    moh: 1, worker_name: "Omar Srour",
    source_link: "https://cnrs.example/api/reports/2026-08-06/05",
    martyrs: "Ali M. (52)",
    note: "Casualty identity pending MoH confirmation at time of entry.",
  },

  // Rejected duplicate/false report — intentionally empty across all groups.
  inc_009: {
    worker_name: "Leila Mansour",
    source_link: "https://t.me/s/southlebnews/839901",
    note: "Rejected: duplicate social post; damage claim could not be verified by local contacts.",
  },

  // Archived historical record — religious/cultural sites and LA.
  inc_010: {
    la: 1, la_did: "D", la_bldg: 1, lam_i: 1, la_ti: 1,
    church: 1, chu_did: "D", chu_n: "St. George Church",
    ceme: 1, ceme_did: "ID", ceme_n: "Blida old cemetery",
    archeo: 1, arch_did: "ID", arch_n: "Roman-era site, eastern hill",
    other: 1, other_did: "ID", other_type: "Livestock shelter",
    warning: 1, building: 1,
    worker_name: "Maya Haddad",
    source_link: "https://ops.example/manual/archive-44",
    note: "Archived after July export reconciliation.",
  },

  // Orchard damage — agriculture, UNIFIL, bridge, construction vehicles.
  inc_011: {
    unifil: 1, un_did: "D", un_v: 1,
    bridge: 1, bridge_blocked: 1, bridge_name: "Houla valley bridge",
    con_veh: 1, tracteur: 1, total_con: 1,
    water: 1, water_did: "ID", water_type: "Irrigation channel",
    olives_trees_d: 120,
    warning: 1,
    worker_name: "Rana Fakih",
    source_link: "https://cnrs.example/api/reports/2026-08-08/02",
    note: "No injuries; damage limited to orchards and one tractor.",
  },

  // Warning shots and drone activity near the fence — LA, motorcycle, drone.
  inc_012: {
    la: 1, la_did: "ID", la_v: 1,
    moto: 1, moto_did: "ID", moto_i: 1,
    drone_f: 1,
    warning: 1,
    worker_name: "Omar Srour",
    source_link: "https://t.me/s/southlebnews/840224",
  },
};

export const emptyDetails: IncidentDetails = {};
