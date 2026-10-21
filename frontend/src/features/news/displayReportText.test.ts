import { describe, expect, it } from "vitest";
import { stripRegisteredSourceHeader } from "./displayReportText";

describe("stripRegisteredSourceHeader", () => {
  it("removes the registered header at the start", () => {
    expect(stripRegisteredSourceHeader("صفحة الإعلامي الشهيد علي شعيب: خبر من الجنوب")).toBe("خبر من الجنوب");
  });

  it("removes a header glued to the report body", () => {
    expect(stripRegisteredSourceHeader("صفحة الإعلامي الشهيد علي شعيبخبر من الجنوب")).toBe("خبر من الجنوب");
  });

  it("matches the header without صفحة and with diacritics", () => {
    expect(stripRegisteredSourceHeader("«الإِعلاميّ الشَّهيدُ عَلِيّ شُعَيْب» خبر من الجنوب")).toBe("خبر من الجنوب");
  });

  it("leaves a body without the registered header unchanged", () => {
    const body = "قصف مدفعي استهدف بلدة في الجنوب";
    expect(stripRegisteredSourceHeader(body)).toBe(body);
  });
});
