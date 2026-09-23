import { describe, expect, it } from "vitest";
import { incidentsNavTarget, roleBaseFromPath } from "./rolePath";

describe("roleBaseFromPath", () => {
  it("maps superadmin and admin path prefixes", () => {
    expect(roleBaseFromPath("/superadmin/incidents")).toBe("/superadmin");
    expect(roleBaseFromPath("/admin/dashboard")).toBe("/admin");
  });
});

describe("incidentsNavTarget", () => {
  const search = "?village=Bint%20Jbeil&page_size=50";

  it("preserves the current query when already on the incidents list", () => {
    expect(incidentsNavTarget("/admin", "/admin/incidents", search)).toBe(
      `/admin/incidents${search}`,
    );
  });

  it("preserves the current query when already on an incident detail page", () => {
    expect(
      incidentsNavTarget("/admin", "/admin/incidents/abc-123", search),
    ).toBe(`/admin/incidents${search}`);
  });

  it("uses a bare list path when entering incidents from outside the section", () => {
    expect(incidentsNavTarget("/admin", "/admin/dashboard", search)).toBe(
      "/admin/incidents",
    );
    expect(incidentsNavTarget("/admin", "/admin/sources", search)).toBe(
      "/admin/incidents",
    );
    expect(
      incidentsNavTarget("/superadmin", "/superadmin/settings", search),
    ).toBe("/superadmin/incidents");
  });
});
