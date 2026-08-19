import { describe, expect, it } from "vitest";
import { formatIncidentFieldValue } from "./formatIncidentFieldValue";
import { fieldGroupForSection } from "./incidentCategorySections";
import { isReported, reportedCount } from "./incidentSchema";

describe("formatIncidentFieldValue", () => {
  it("formats DID values distinctly from raw strings", () => {
    expect(formatIncidentFieldValue({ name: "la_did", kind: "did" }, "D")).toBe(
      "Direct",
    );
    expect(formatIncidentFieldValue({ name: "la_did", kind: "did" }, "ID")).toBe(
      "Indirect",
    );
  });

  it("formats flags as yes/no", () => {
    expect(formatIncidentFieldValue({ name: "la", kind: "flag" }, 1)).toBe("Yes");
  });
});

describe("incident category section field selection", () => {
  it("maps lebanese_army section to the LA field group", () => {
    const group = fieldGroupForSection("lebanese_army");
    expect(group?.name).toBe("Lebanese Army (LA)");
  });

  it("omits DID fields when the controlling gate is inactive", () => {
    const group = fieldGroupForSection("health_center");
    const didField = group!.fields.find((field) => field.name === "hc_did");
    expect(isReported({ hc: 0, hc_did: "D" }, didField!)).toBe(false);
  });

  it("reports seeded LA fields from the Bug A verification payload", () => {
    const group = fieldGroupForSection("lebanese_army")!;
    const details = { la: 1, la_did: "D", lam_d: 2, la_td: 2 };

    expect(reportedCount(details, group)).toBe(4);
    expect(
      group.fields
        .filter((field) => isReported(details, field))
        .map((field) => field.name),
    ).toEqual(["la", "la_did", "lam_d", "la_td"]);
  });

  it("keeps empty sections at zero reported fields", () => {
    const group = fieldGroupForSection("press")!;
    expect(reportedCount({}, group)).toBe(0);
  });
});
