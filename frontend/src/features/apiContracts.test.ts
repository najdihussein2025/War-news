import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../lib/apiClient";
import { login } from "./auth/api";
import { createAirViolation, deleteAirViolation, updateAirViolation } from "./airViolations/api";
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

  it("uses the expected Air Violations CRUD endpoints", async () => {
    const payload = { condition_id: 35, caza_en: "Sour", event_date: "2026-08-18", khabar: "News" };
    vi.mocked(client.post).mockResolvedValue({ data: { id: 8 } });
    vi.mocked(client.put).mockResolvedValue({ data: { id: 8 } });
    await createAirViolation(payload);
    await updateAirViolation(8, payload);
    await deleteAirViolation(8);
    expect(client.post).toHaveBeenCalledWith("/api/air-violations", payload);
    expect(client.put).toHaveBeenCalledWith("/api/air-violations/8", payload);
    expect(client.delete).toHaveBeenCalledWith("/api/air-violations/8");
  });
});
