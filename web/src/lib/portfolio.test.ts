import { expect, test } from "vitest";

import { sum } from "@/lib/decimal";
import { cashTarget, prefillWeights, saveOrder } from "@/lib/portfolio";

test("weights are each value over priced assets plus cash, rounded down", () => {
  const weights = prefillWeights("100", [
    { asset: "BTC", value: "300", locked: false },
    { asset: "ETH", value: "600", locked: false },
  ]);
  expect(weights.get("BTC")).toBe("30");
  expect(weights.get("ETH")).toBe("60");
});

test("thirds round down and never sum above 100", () => {
  const weights = prefillWeights("0", [
    { asset: "A", value: "1", locked: false },
    { asset: "B", value: "1", locked: false },
    { asset: "C", value: "1", locked: false },
  ]);
  expect([...weights.values()]).toEqual(["33.3", "33.3", "33.3"]);
  expect(sum([...weights.values()])).toBe("99.9");
});

test("an unpriced or locked holding gets no weight and is not counted", () => {
  const weights = prefillWeights("50", [
    { asset: "BTC", value: "50", locked: false },
    { asset: "DOT", value: null, locked: false },
    { asset: "ETH.S", value: null, locked: true },
  ]);
  expect(weights.get("BTC")).toBe("50");
  expect(weights.has("DOT")).toBe(false);
  expect(weights.has("ETH.S")).toBe(false);
});

test("an empty account gives zero weights", () => {
  const weights = prefillWeights("0", [
    { asset: "BTC", value: "0", locked: false },
  ]);
  expect(weights.get("BTC")).toBe("0");
});

test("cash is 100 minus the targets", () => {
  expect(cashTarget(["30", "60.5"])).toBe("9.5");
  expect(cashTarget(["60", "50"])).toBe("-10");
});

test("saving deletes first, then lowers, then raises", () => {
  const order = saveOrder(
    new Map([
      ["BTC", "60"],
      ["ETH", "40"],
      ["DOT", "5"],
    ]),
    new Map([
      ["BTC", "40"],
      ["ETH", "55"],
      ["SOL", "5"],
    ]),
  );
  expect(order.deletes).toEqual(["DOT"]);
  expect(order.puts).toEqual([
    { asset: "BTC", target: "40" },
    { asset: "SOL", target: "5" },
    { asset: "ETH", target: "55" },
  ]);
});
