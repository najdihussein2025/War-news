import { describe, expect, it } from "vitest";
import { assignedTotal, buildResolutionEntries, canSubmitResolution, dismissReasonError, filtersFromSearch, filtersToSearch, isOverTotal, mapApiError, mapFieldErrors, unresolvedSiblingIds } from "./logic";

describe("casualty check logic", () => {
  it("reads defaults and persists filters in the query string", () => {
    expect(filtersFromSearch("")).toEqual({ status: "open", reason: undefined, dateFrom: undefined, dateTo: undefined, q: undefined });
    const filters = filtersFromSearch("?status=resolved&reason=count_missing&date_from=2026-01-01&date_to=2026-01-31&q=Tyre");
    expect(filtersToSearch(filters).toString()).toBe("status=resolved&reason=count_missing&date_from=2026-01-01&date_to=2026-01-31&q=Tyre");
  });

  it("calculates allocation totals and detects an over-allocation", () => {
    const values = { a: { total_deaths: "2", total_injuries: "" }, b: { total_deaths: "3", total_injuries: "4" } };
    expect(assignedTotal(values, "total_deaths")).toBe(5);
    expect(assignedTotal(values, "total_injuries")).toBe(4);
    expect(isOverTotal(values, "total_deaths", 4)).toBe(true);
    expect(isOverTotal(values, "total_deaths", 5)).toBe(false);
    expect(canSubmitResolution(false, 2, true)).toBe(false);
  });

  it("allows confirm unknown without numeric entries", () => {
    expect(canSubmitResolution(true, 0, false)).toBe(true);
    expect(canSubmitResolution(false, 0, false)).toBe(false);
  });

  it("requires a dismissal reason of at least three characters", () => {
    expect(dismissReasonError("no")).toBe("Enter at least 3 characters.");
    expect(dismissReasonError("duplicate")).toBeUndefined();
  });

  it("maps API validation errors", () => {
    expect(mapApiError({ response: { data: { detail: [{ msg: "Value error, Provide at least one entry" }] } } })).toBe("Provide at least one entry");
    expect(mapApiError({ response: { data: { detail: "Assigned deaths exceeds total" } } })).toBe("Assigned deaths exceeds total");
  });

  it("builds entries containing all supplied casualty dimensions", () => {
    expect(buildResolutionEntries({ tyre: { total_deaths: "2", male_d: "1", children_d: "1" } })).toEqual([
      { incident_id: "tyre", total_deaths: 2, male_d: 1, children_d: 1 },
    ]);
  });

  it("maps structured validation errors to incident fields and summary", () => {
    const mapped = mapFieldErrors({ response: { data: { errors: [
      { incident_id: "tyre", field: "total_deaths", code: "over_total", message: "Too many deaths." },
      { incident_id: null, field: "entries", code: "required", message: "Add an entry." },
    ] } } });
    expect(mapped.fields).toEqual({ "tyre.total_deaths": "Too many deaths." });
    expect(mapped.summary).toEqual(["Add an entry."]);
  });
});

describe("aggregate toll partial save", () => {
  it("keeps the panel on the sibling locations this save did not resolve", () => {
    const siblings = ["a", "b", "c", "d", "e"];
    expect(unresolvedSiblingIds(siblings, [{ incident_id: "d", resolved: true }])).toEqual(["a", "b", "c", "e"]);
    expect(unresolvedSiblingIds(siblings, [{ incident_id: "d", resolved: false }])).toEqual(siblings);
    expect(unresolvedSiblingIds(["a"], [{ incident_id: "a", resolved: true }])).toEqual([]);
  });
});
