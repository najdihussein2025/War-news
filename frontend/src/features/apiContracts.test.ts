import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../lib/apiClient";
import { login } from "./auth/api";
import { changeAccountPassword } from "./accounts/api";
import {
  acquireAirViolationEditLock,
  createAirViolation,
  deleteAirViolation,
  releaseAirViolationEditLock,
  updateAirViolation,
} from "./airViolations/api";
import {
  acquireIncidentEditLock,
  createIncident,
  deleteIncident,
  getConditions,
  getIncidentById,
  getIncidentDuplicateCandidate,
  getIncidents,
  getVillages,
  importIncidents,
  releaseIncidentEditLock,
  resolveIncidentDuplicate,
  updateIncident,
  updateIncidentDetails,
} from "./news/api";
import { getContentSource, getContentSources } from "./sources/api";
import { getMapEvents } from "./map/api";

vi.mock("../lib/apiClient", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}));

const client = vi.mocked(apiClient);

describe("frontend API contracts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("logs in through the cookie-enabled endpoint", async () => {
    vi.mocked(client.post).mockResolvedValue({ data: { user: { id: "1", username: "admin" }, role: "super_admin" } });
    await login("admin", "secret");
    expect(client.post).toHaveBeenCalledWith("/auth/login", { username: "admin", password: "secret" });
  });

  it("loads and safely encodes content-source requests", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: [] });
    await getContentSources({ platform: "telegram", search: "news" });
    await getContentSource("telegram", "account/name");
    expect(client.get).toHaveBeenNthCalledWith(1, "/content-sources", { params: { platform: "telegram", search: "news" } });
    expect(client.get).toHaveBeenNthCalledWith(2, "/content-sources/telegram/account%2Fname");
  });

  it("loads active conditions for the incidents filter", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: [] });
    await getConditions();
    expect(client.get).toHaveBeenCalledWith("/conditions");
  });

  it("loads active villages for the create incident form", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: [] });
    await getVillages();
    expect(client.get).toHaveBeenCalledWith("/villages");
  });

  it("loads the unified map with repeated event-type filters", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: { items: [], unmapped_count: 0, truncated: false } });
    await getMapEvents({
      dateFrom: "2026-08-27",
      dateTo: "2026-08-28",
      eventTypes: ["incident", "air_violation"],
    });
    expect(client.get).toHaveBeenCalledWith(
      "/map/events?event_date_from=2026-08-27&event_date_to=2026-08-28&event_type=incident&event_type=air_violation",
    );
  });

  it("uses normalized incident endpoints without duplicating the api base path", async () => {
    const payload = {
      title: "Shelling",
      condition_id: 5,
      source_id: 3,
      village_id: 976,
      event_date: "2026-08-19",
      event_time: "18:22:33",
    };
    const file = new File(["sheet"], "incidents.xlsx");

    vi.mocked(client.get).mockResolvedValue({ data: { items: [], total: 0 } });
    vi.mocked(client.post).mockResolvedValue({ data: { id: "42" } });
    vi.mocked(client.put).mockResolvedValue({ data: { id: "42" } });
    vi.mocked(client.patch).mockResolvedValue({ data: { id: "42" } });

    await getIncidents({ limit: 25, offset: 0 });
    await getIncidentById("42");
    await createIncident(payload as never);
    await updateIncident("42", payload as never);
    await updateIncidentDetails("42", { killed: 1 }, 7);
    await deleteIncident("42", 7);
    await importIncidents(file);

    expect(client.get).toHaveBeenNthCalledWith(1, "/incidents?limit=25&offset=0");
    expect(client.get).toHaveBeenNthCalledWith(2, "/incidents/42");
    expect(client.post).toHaveBeenNthCalledWith(1, "/incidents", payload);
    expect(client.put).toHaveBeenCalledWith("/incidents/42", payload);
    expect(client.patch).toHaveBeenCalledWith("/incidents/42/details", { fields: { killed: 1 }, version: 7 });
    expect(client.delete).toHaveBeenCalledWith("/incidents/42", { params: { version: 7 } });
    expect(client.post).toHaveBeenNthCalledWith(2, "/incidents/import", expect.any(FormData));
  });

  it("uses the expected Air Violations CRUD endpoints", async () => {
    const payload = { condition_id: 35, caza_en: "Sour", event_date: "2026-08-18", khabar: "News" };
    const updatePayload = { ...payload, version: 3 };
    vi.mocked(client.post).mockResolvedValue({ data: { id: 8 } });
    vi.mocked(client.put).mockResolvedValue({ data: { id: 8 } });
    await createAirViolation(payload);
    await updateAirViolation(8, updatePayload);
    await deleteAirViolation(8, 4);
    await acquireAirViolationEditLock(8);
    await releaseAirViolationEditLock(8);
    expect(client.post).toHaveBeenCalledWith("/air-violations", payload);
    expect(client.put).toHaveBeenCalledWith("/air-violations/8", updatePayload);
    expect(client.delete).toHaveBeenCalledWith("/air-violations/8", { params: { version: 4 } });
    expect(client.post).toHaveBeenCalledWith("/air-violations/8/edit-lock");
    expect(client.delete).toHaveBeenCalledWith("/air-violations/8/edit-lock");
  });

  it("sends the account version when changing a password", async () => {
    await changeAccountPassword("user-1", {
      current_password: "old-password",
      new_password: "new-password",
      version: 7,
    });
    expect(client.patch).toHaveBeenCalledWith("/accounts/user-1/password", {
      current_password: "old-password",
      new_password: "new-password",
      version: 7,
    });
  });

  it("uses versioned Incident mutation and edit-lock endpoints", async () => {
    vi.mocked(client.post).mockResolvedValue({ data: { id: "incident-1" } });
    vi.mocked(client.patch).mockResolvedValue({ data: { id: "incident-1" } });
    await acquireIncidentEditLock("incident-1");
    await updateIncidentDetails("incident-1", { lam_d: 2 }, 4);
    await deleteIncident("incident-1", 5);
    await releaseIncidentEditLock("incident-1");
    expect(client.post).toHaveBeenCalledWith("/incidents/incident-1/edit-lock");
    expect(client.patch).toHaveBeenCalledWith("/incidents/incident-1/details", { fields: { lam_d: 2 }, version: 4 });
    expect(client.delete).toHaveBeenCalledWith("/incidents/incident-1", { params: { version: 5 } });
    expect(client.delete).toHaveBeenCalledWith("/incidents/incident-1/edit-lock");
  });

  it("loads and resolves pending incident duplicates", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: { match_id: 8 } });
    vi.mocked(client.post).mockResolvedValue({ data: { canonical_incident_id: "main-1" } });

    await getIncidentDuplicateCandidate("incident-1");
    await resolveIncidentDuplicate("incident-1", 8, "false_positive", 3);

    expect(client.get).toHaveBeenCalledWith("/incidents/incident-1/duplicate-candidate");
    expect(client.post).toHaveBeenCalledWith(
      "/incidents/incident-1/duplicate-resolution",
      { match_id: 8, decision: "false_positive", version: 3 },
    );
  });
});
