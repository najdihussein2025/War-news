import { describe, expect, it } from "vitest";
import { casualtyChip, casualtyHeadline, compactCasualtyText } from "./casualtyPresentation";

describe("casualty presentation", () => {
  it("renders the Haddatha payload consistently", () => {
    const payload = { killed: null, injured: 2, breakdown: { children_injured: 1 }, status: "reported" };
    expect(casualtyHeadline(payload)).toBe("2 injured");
    expect(casualtyChip("children_injured", 1)).toBe("1 child injured");
  });

  it("distinguishes unknown, explicit zero, and contradictory data", () => {
    expect(casualtyHeadline({ killed: null, injured: null, status: "none" })).toBe("No casualties reported");
    expect(casualtyHeadline({ killed: 0, injured: 0, status: "explicit_none" })).toBe("No casualties (stated)");
    expect(casualtyHeadline({ killed: null, injured: null, breakdown: { men_injured: 2 } })).toBe("Casualty data needs check");
    expect(compactCasualtyText(null, 2)).toBe("2 injuries");
  });
});
