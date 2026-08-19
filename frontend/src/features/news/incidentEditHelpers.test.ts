import { describe, expect, it } from "vitest";
import { fieldGroupForSection } from "./incidentCategorySections";
import {
  applyGateOff,
  initialFormDetails,
  isGateActive,
  validateSectionForm,
} from "./incidentEditHelpers";

describe("incident edit gating helpers", () => {
  it("clears LA dependent fields when the la gate is turned off", () => {
    const group = fieldGroupForSection("lebanese_army")!;
    const details = { la: 1, la_did: "D", lam_d: 2, la_bldg: 1 };

    const next = applyGateOff(details, group, "la");

    expect(isGateActive(next, "la")).toBe(false);
    expect(next.la_did).toBe(0);
    expect(next.lam_d).toBe(0);
    expect(next.la_bldg).toBe(0);
  });

  it("requires DID when gate is active on save validation", () => {
    const group = fieldGroupForSection("lebanese_army")!;
    const invalid = { la: 1, la_did: "" };
    const valid = { la: 1, la_did: "D" };

    expect(validateSectionForm(group, invalid)).toMatch(/damage type is required/i);
    expect(validateSectionForm(group, valid)).toBeNull();
  });

  it("seeds blank defaults for empty sections so gates can be activated", () => {
    const group = fieldGroupForSection("hospital")!;
    const form = initialFormDetails(group, null);

    expect(form.hosp).toBe(0);
    expect(form.hos_did).toBe(0);
    expect(form.hos_n).toBe("");
  });
});
