export type IncidentStatus = "approved" | "rejected" | "archived";
export type IncidentSourceType = "Telegram" | "API" | "Manual";
export type DuplicateFlag = "none" | "possible";

export type MockIncident = {
  id: string;
  village: string;
  condition: string;
  action: string;
  event_date: string;
  khabar: string;
  source: IncidentSourceType;
  source_reference: string;
  matched: boolean;
  duplicate_flag: DuplicateFlag;
  status: IncidentStatus;
  reviewed_by: string | null;
  created_at: string;
};

export const mockIncidents: MockIncident[] = [
  ["inc_001", "Aitaroun", "Shelling", "Impact", "2026-08-10T07:30:00+03:00", "Artillery impact reported near residential edge with smoke visible from the eastern ridge.", "Telegram", "tg:842199", true, "possible", "approved", "Auto-published", "2026-08-10T08:05:00+03:00"],
  ["inc_002", "Khiam", "Airstrike", "Damage", "2026-08-10T06:15:00+03:00", "Local reports describe structural damage to two adjacent homes after an early morning strike.", "API", "cnrs:2026-08-10:09", true, "none", "approved", "Auto-published", "2026-08-10T06:40:00+03:00"],
  ["inc_003", "Marjayoun", "Drone", "Overflight", "2026-08-09T21:10:00+03:00", "Drone activity observed above the western neighborhoods for roughly twenty minutes.", "Manual", "manual:ops-118", false, "possible", "approved", "Auto-published", "2026-08-09T21:55:00+03:00"],
  ["inc_004", "Bint Jbeil", "Shelling", "Injury", "2026-08-09T19:45:00+03:00", "Municipal source reports injuries after shell fragments reached a roadside shop.", "Telegram", "tg:842011", true, "none", "approved", "Auto-published", "2026-08-09T20:02:00+03:00"],
  ["inc_005", "Naqoura", "Naval fire", "Impact", "2026-08-09T16:20:00+03:00", "Explosions heard near coastal farmland; no confirmed casualty figures yet.", "API", "cnrs:2026-08-09:22", false, "possible", "approved", "Auto-published", "2026-08-09T17:10:00+03:00"],
  ["inc_006", "Taybeh", "Shelling", "Displacement", "2026-08-08T14:00:00+03:00", "Families temporarily relocated after repeated impacts near the southern road.", "Telegram", "tg:841772", true, "none", "approved", "Auto-published", "2026-08-08T14:45:00+03:00"],
  ["inc_007", "Yaroun", "Airstrike", "Infrastructure", "2026-08-07T11:35:00+03:00", "Power line damage reported by residents following a targeted strike.", "Manual", "manual:ops-103", true, "none", "approved", "Maya Haddad", "2026-08-07T12:00:00+03:00"],
  ["inc_008", "Mays al-Jabal", "Drone", "Casualty", "2026-08-06T09:25:00+03:00", "A vehicle was reportedly struck near the hospital road; casualty details pending confirmation.", "API", "cnrs:2026-08-06:05", true, "possible", "approved", "Auto-published", "2026-08-06T10:05:00+03:00"],
  ["inc_009", "Rmeish", "Shelling", "False report", "2026-08-03T18:20:00+03:00", "Duplicate social post claimed damage that could not be verified by local contacts.", "Telegram", "tg:839901", true, "possible", "rejected", "Leila Mansour", "2026-08-03T19:00:00+03:00"],
  ["inc_010", "Blida", "Airstrike", "Archived", "2026-07-29T15:10:00+03:00", "Historical record archived after export and reconciliation.", "Manual", "manual:archive-44", true, "none", "archived", "Maya Haddad", "2026-07-29T16:30:00+03:00"],
  ["inc_011", "Houla", "Shelling", "Agriculture", "2026-08-08T08:10:00+03:00", "Orchard damage reported with no immediate injuries.", "API", "cnrs:2026-08-08:02", true, "none", "approved", "Auto-published", "2026-08-08T09:00:00+03:00"],
  ["inc_012", "Adaisseh", "Drone", "Warning", "2026-08-05T22:00:00+03:00", "Residents reported warning shots and prolonged drone activity near the border fence.", "Telegram", "tg:840224", false, "possible", "approved", "Auto-published", "2026-08-05T22:35:00+03:00"],
].map((item) => {
  const [id, village, condition, action, event_date, khabar, source, source_reference, matched, duplicate_flag, status, reviewed_by, created_at] = item;
  return {
    id,
    village,
    condition,
    action,
    event_date,
    khabar,
    source,
    source_reference,
    matched,
    duplicate_flag,
    status,
    reviewed_by,
    created_at,
  } as MockIncident;
});
