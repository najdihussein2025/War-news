import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("analytics CSV", () => {
  it("quotes commas, quotes and newlines and leaves plain values alone", () => {
    expect(toCsv(["Area", "Value"], [["Sour, South", 3], ['He said "x"', null], ["two\nlines", 0]]))
      .toBe('Area,Value\r\n"Sour, South",3\r\n"He said ""x""",\r\n"two\nlines",0');
  });

  it("keeps Arabic text as is", () => {
    expect(toCsv(["name"], [["النبطية"]])).toBe("name\r\nالنبطية");
  });
});
