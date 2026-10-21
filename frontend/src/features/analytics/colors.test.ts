import { describe, expect, it } from "vitest";
import { classColor, classIndex, colorForValue, legendEntries, NO_DATA_COLOR, quantileBreaks, SEQUENTIAL, textOn } from "./colors";

describe("quantile color scale", () => {
  it("uses each distinct value as a class when there are few", () => {
    expect(quantileBreaks([1, 1, 3, 9])).toEqual([1, 3, 9]);
  });

  it("splits many values into at most 7 increasing classes", () => {
    const values = Array.from({ length: 100 }, (_, i) => i + 1);
    const breaks = quantileBreaks(values);
    expect(breaks).toHaveLength(7);
    expect([...breaks].sort((a, b) => a - b)).toEqual(breaks);
    expect(breaks[6]).toBe(100);
  });

  it("collapses duplicate quantiles", () => {
    const breaks = quantileBreaks([...Array(50).fill(1), ...Array.from({ length: 20 }, (_, i) => i + 2)]);
    expect(new Set(breaks).size).toBe(breaks.length);
  });

  it("ignores zero, negative and NaN values", () => {
    expect(quantileBreaks([0, -1, Number.NaN])).toEqual([]);
  });

  it("maps values to classes and colors, with grey for no data", () => {
    const breaks = [2, 5, 10];
    expect(classIndex(1, breaks)).toBe(0);
    expect(classIndex(2, breaks)).toBe(0);
    expect(classIndex(6, breaks)).toBe(2);
    expect(classIndex(999, breaks)).toBe(2);
    expect(classIndex(0, breaks)).toBe(-1);
    expect(colorForValue(0, breaks)).toBe(NO_DATA_COLOR);
    expect(colorForValue(1, breaks)).toBe(SEQUENTIAL[0]);
    expect(colorForValue(10, breaks)).toBe(SEQUENTIAL[6]);
  });

  it("spreads fewer classes over the full palette and keeps the order", () => {
    const colors = [0, 1, 2, 3].map((i) => classColor(i, 4));
    expect(colors.map((c) => SEQUENTIAL.indexOf(c as never))).toEqual([0, 2, 4, 6]);
  });

  it("builds legend ranges that do not overlap", () => {
    expect(legendEntries([2, 5, 10]).map((e) => [e.from, e.to])).toEqual([[1, 2], [3, 5], [6, 10]]);
  });

  it("chooses readable text colors", () => {
    expect(textOn(SEQUENTIAL[0])).toBe("#0b2236");
    expect(textOn(SEQUENTIAL[6])).toBe("#ffffff");
  });
});
