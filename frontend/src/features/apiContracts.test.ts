import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../lib/apiClient";
import { login } from "./auth/api";
import { acquireAirViolationEditLock, createAirViolation, deleteAirViolation, releaseAirViolationEditLock, updateAirViolation } from "./airViolations/api";
import { getConditions, getVillages } from "./news/api";
import { getContentSource, getContentSources } from "./sources/api";

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
    expect(client.get).toHaveBeenNthCalledWith(1, "/api/content-sources", { params: { platform: "telegram", search: "news" } });
    expect(client.get).toHaveBeenNthCalledWith(2, "/api/content-sources/telegram/account%2Fname");
  });

  it("loads active conditions for the incidents filter", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: [] });
    await getConditions();
    expect(client.get).toHaveBeenCalledWith("/api/conditions");
  });

  it("loads active villages for the create incident form", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: [] });
    await getVillages();
    expect(client.get).toHaveBeenCalledWith("/api/villages");
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
    expect(client.post).toHaveBeenCalledWith("/api/air-violations", payload);
    expect(client.put).toHaveBeenCalledWith("/api/air-violations/8", updatePayload);
    expect(client.delete).toHaveBeenCalledWith("/api/air-violations/8", { params: { version: 4 } });
    expect(client.post).toHaveBeenCalledWith("/api/air-violations/8/edit-lock");
    expect(client.delete).toHaveBeenCalledWith("/api/air-violations/8/edit-lock");
  });
});
