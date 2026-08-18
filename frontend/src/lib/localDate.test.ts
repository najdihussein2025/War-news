import { describe, expect, it } from "vitest";
import { getBeirutDate } from "./localDate";

describe("getBeirutDate", () => {
  it("uses Beirut's calendar date when UTC is still on the previous day", () => {
    expect(getBeirutDate(0, new Date("2026-08-17T21:30:00.000Z"))).toBe("2026-08-18");
  });

  it("returns the previous Beirut calendar day", () => {
    expect(getBeirutDate(-1, new Date("2026-08-17T21:30:00.000Z"))).toBe("2026-08-17");
  });
});
