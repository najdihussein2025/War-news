import { MemoryRouter } from "react-router-dom";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReasonChips, WhyNeedsReviewSection, summarizeVerificationReasons } from "./verificationReasons";
import type { IncidentDetail } from "./types";

describe("summarizeVerificationReasons", () => {
  it("dedupes duplicate fragments and keeps the max score", () => {
    const summaries = summarizeVerificationReasons(
      "Possible duplicate of incident #1234 score 0.72 | Possible duplicate of incident #5678 score 1.00",
    );

    expect(summaries).toHaveLength(1);
    expect(summaries[0]).toMatchObject({
      key: "duplicate",
      label: "Duplicate · 100%",
      score: 1,
    });
  });

  it("splits multi-incident and multi-signal reason text", () => {
    const summaries = summarizeVerificationReasons(
      "Low confidence village match; No condition matched | Message mentions flare bombs and strikes",
    );

    expect(summaries.map((summary) => summary.key)).toEqual([
      "low_confidence_village",
      "no_condition_match",
      "flare_strike_wording",
    ]);
  });

  it("maps unknown fragments to other and accepts empty input", () => {
    expect(summarizeVerificationReasons("Manual review requested")[0].key).toBe("other");
    expect(summarizeVerificationReasons(null)).toEqual([]);
    expect(summarizeVerificationReasons("")).toEqual([]);
  });
});

describe("verification reason UI", () => {
  it("renders no more than two visible chips plus a hidden-count chip", () => {
    const longReason =
      "Possible duplicate score 1.00; Low confidence village match; No condition matched; casualties aggregate not per-village";
    const html = renderToStaticMarkup(
      <ReasonChips summaries={summarizeVerificationReasons(longReason)} />,
    );

    expect(html).toContain("Duplicate · 100%");
    expect(html).toContain("Low-confidence village");
    expect(html).toContain("+2");
    expect(html).not.toContain("Possible duplicate score 1.00");
  });

  it("renders detail review lines once for a deduped incident", () => {
    const incident = {
      id: "current",
      village: "Aita",
      condition: "Strike",
      khabar: "النص الكامل",
      verification_reason:
        "Possible duplicate of incident #1234 score 1.00 | Possible duplicate of incident #1234 score 1.00; Low confidence village match",
    } as IncidentDetail;

    const html = renderToStaticMarkup(
      <MemoryRouter>
        <WhyNeedsReviewSection incident={incident} roleBase="/admin" search="" />
      </MemoryRouter>,
    );

    expect(html).toContain("Why this needs review");
    expect(html.match(/Looks like a duplicate/g)).toHaveLength(1);
    expect(html.match(/Village match is low confidence/g)).toHaveLength(1);
    expect(html).toContain("النص الكامل");
  });
});
