import { beforeEach, describe, expect, it, vi } from "vitest";

describe("authStore", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("removes legacy bearer tokens from persisted browser state", async () => {
    localStorage.setItem("lebanon-news-auth", JSON.stringify({
      user: { id: "1", username: "admin" },
      role: "super_admin",
      token: "legacy-secret-token",
    }));

    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().hydrateFromStorage();

    expect(localStorage.getItem("lebanon-news-auth")).not.toContain("legacy-secret-token");
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("persists only non-sensitive user and role metadata after login", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().login({
      user: { id: "1", username: "admin" },
      role: "super_admin",
    });

    expect(JSON.parse(localStorage.getItem("lebanon-news-auth") ?? "{}")).toEqual({
      user: { id: "1", username: "admin" },
      role: "super_admin",
    });
  });
});
