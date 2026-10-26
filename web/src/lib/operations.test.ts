import { expect, test } from "vitest";

import {
  countOrders,
  legLine,
  legStatus,
  outcomeSentence,
  sentAnything,
} from "@/lib/operations";

test("a leg is told as a sentence in the account's fiat", () => {
  expect(legLine({ side: "BUY", asset: "BTC", amount_fiat: "50" }, "EUR")).toBe(
    "Buy BTC for €50.00",
  );
  expect(
    legLine({ side: "sell", asset: "ETH", amount_fiat: "20" }, "EUR"),
  ).toBe("Sell ETH for €20.00");
});

test("a leg's status is told in words, with the reason when there is one", () => {
  const s = (
    status: string,
    error: string | null = null,
    note: string | null = null,
  ) => legStatus({ status, error, note });
  expect(s("VALIDATED")).toBe("Kraken accepts it");
  expect(s("REJECTED", "volume too low")).toBe(
    "Kraken refuses it: volume too low",
  );
  expect(s("REJECTED")).toBe("Kraken refuses it");
  expect(s("SKIPPED", null, "below minimum")).toBe("Skipped: below minimum");
  expect(s("SKIPPED")).toBe("Skipped");
  expect(s("UNCHECKED")).toBe("Not checked by Kraken");
  expect(s("FILLED")).toBe("Filled");
  expect(s("FAILED", "insufficient funds")).toBe("Failed: insufficient funds");
  expect(s("FAILED")).toBe("Failed");
  expect(s("PENDING")).toBe("Sent; the result is not known yet");
  expect(s("WHATEVER")).toBe("WHATEVER");
});

test("an outcome is told in a sentence", () => {
  expect(outcomeSentence("DONE")).toBe("Every order was filled.");
  expect(outcomeSentence("PARTIAL")).toBe(
    "Kraken refused some orders; the others were filled.",
  );
  expect(outcomeSentence("STOPPED")).toBe(
    "The result of an order is not known yet. CoinPilot checks it before the next operation.",
  );
  expect(outcomeSentence("ERROR")).toBe(
    "The operation failed. Nothing more was sent.",
  );
  expect(outcomeSentence("NOTHING_TO_DO")).toBe("Nothing to do.");
  expect(outcomeSentence("PROPOSED")).toBe(
    "A rebalance is waiting for your approval.",
  );
  expect(outcomeSentence("ODD")).toBe("ODD");
});

test("orders are counted with their plural", () => {
  expect(countOrders(0)).toBe("0 orders");
  expect(countOrders(1)).toBe("1 order");
  expect(countOrders(2)).toBe("2 orders");
});

test("something was sent when a leg is filled or pending", () => {
  expect(sentAnything([{ status: "FILLED" }])).toBe(true);
  expect(sentAnything([{ status: "PENDING" }])).toBe(true);
  expect(sentAnything([{ status: "FAILED" }, { status: "SKIPPED" }])).toBe(
    false,
  );
  expect(sentAnything([])).toBe(false);
});
