import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VillageMatchNotice } from "./VillageMatchNotice";

describe("VillageMatchNotice", () => {
  it("shows an uncertain match and alternate village", () => {
    const html = renderToStaticMarkup(
      <VillageMatchNotice
        village_review_required
        any_village_low_confidence
        resolved_by_geo_context={false}
        alternate_candidate_village_name="Knisse Baalbek"
      />,
    );

    expect(html).toContain("Village match uncertain");
    expect(html).toContain("also possible: Knisse Baalbek");
  });

  it("shows the nearby anchor for a geo-context resolution", () => {
    const html = renderToStaticMarkup(
      <VillageMatchNotice
        village_review_required={false}
        any_village_low_confidence={false}
        resolved_by_geo_context
        geo_context_anchor_village_name="Harouf En-Nabatiyeh"
      />,
    );

    expect(html).toContain("Nearby-location match");
    expect(html).toContain(
      "Village confirmed via nearby location match (Harouf En-Nabatiyeh)",
    );
  });

  it("renders nothing for an ordinary confident match", () => {
    const html = renderToStaticMarkup(
      <VillageMatchNotice
        village_review_required={false}
        any_village_low_confidence={false}
        resolved_by_geo_context={false}
      />,
    );

    expect(html).toBe("");
  });
});
