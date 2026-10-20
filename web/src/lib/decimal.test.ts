import { expect, test } from "vitest";

import {
  compare,
  formatMoney,
  formatPercent,
  parseDecimal,
  subtract,
  sum,
} from "@/lib/decimal";

test.each([
  ["12.5", "12.5"],
  ["12,5", "12.5"],
  [" 12,50 ", "12.5"],
  ["007", "7"],
  ["0", "0"],
  ["0.0", "0"],
  ["100", "100"],
  ["1.234", null],
  ["", null],
  ["-1", null],
  ["1e2", null],
  ["1.000,5", null],
  ["12.", null],
  [",5", null],
  ["abc", null],
])("parseDecimal(%j, 2) is %j", (text, expected) => {
  expect(parseDecimal(text, 2)).toBe(expected);
});

test("parseDecimal honours the number of places", () => {
  expect(parseDecimal("1.25", 1)).toBeNull();
  expect(parseDecimal("1.2", 1)).toBe("1.2");
});

test("sum, subtract and compare are exact", () => {
  expect(sum(["33.3", "66.6"])).toBe("99.9");
  expect(sum([])).toBe("0");
  expect(subtract("100", "100.5")).toBe("-0.5");
  expect(compare("10", "9.99")).toBe(1);
  expect(compare("1", "1.0")).toBe(0);
  expect(compare("1", "2")).toBe(-1);
});

test("formatMoney formats a decimal string without float loss", () => {
  expect(formatMoney("1234.5", "EUR")).toBe("€1,234.50");
  expect(formatMoney("0.1", "USD")).toBe("$0.10");
  expect(formatMoney("12345678901234567.89", "EUR")).toBe(
    "€12,345,678,901,234,567.89",
  );
});

test("formatPercent shows the canonical value", () => {
  expect(formatPercent("1.0")).toBe("1 %");
  expect(formatPercent("12.50")).toBe("12.5 %");
});
