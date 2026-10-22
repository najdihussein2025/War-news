import { isValidElement, type ReactElement } from "react";
import { matchRoutes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AnalyticsLayout } from "../features/analytics/layout/AnalyticsLayout";
import { ROLES } from "../constants/roles";
import { AppShell } from "./AppShell";
import { createRoutes } from "./routes";

const layoutFor = (path: string) => {
  const matches = matchRoutes(createRoutes(), path) ?? [];
  const guard = matches[0]?.route.element as ReactElement<{ roles: string[]; children: ReactElement }>;
  return { guard, layout: isValidElement(guard?.props.children) ? guard.props.children.type : null };
};

describe("analytics routes", () => {
  it.each([
    ["/superadmin/analytics", ROLES.SUPER_ADMIN],
    ["/admin/analytics", ROLES.ADMIN],
  ])("%s renders the full-width layout behind the same role guard", (path, role) => {
    const { guard, layout } = layoutFor(path);
    expect(layout).toBe(AnalyticsLayout);
    expect(guard.props.roles).toEqual([role]);
  });

  it("keeps every other page inside the admin shell", () => {
    expect(layoutFor("/superadmin/dashboard").layout).toBe(AppShell);
    expect(layoutFor("/admin/incidents").layout).toBe(AppShell);
  });
});
