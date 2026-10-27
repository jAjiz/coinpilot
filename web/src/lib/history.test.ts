import { expect, test } from "vitest";
import type { components } from "@/api/schema";
import {
  messagesOf,
  orderLine,
  orderStatus,
  runStatus,
  runTitle,
} from "./history";

test("a run is titled by its operation and its trigger", () => {
  expect(runTitle({ operation: "INVEST", trigger: "SCHEDULER" })).toBe(
    "Invest · scheduled",
  );
  expect(runTitle({ operation: "PROPOSE", trigger: "API" })).toBe(
    "Rebalance check · by you",
  );
  expect(runTitle({ operation: "APPROVE", trigger: "API" })).toBe(
    "Approved rebalance · by you",
  );
  expect(runTitle({ operation: "REBALANCE", trigger: "SCHEDULER" })).toBe(
    "Automatic rebalance · scheduled",
  );
  expect(runTitle({ operation: null, trigger: "API" })).toBe("Run · by you");
  expect(runTitle({ operation: "INVEST", trigger: null })).toBe("Invest");
  expect(runTitle({ operation: null, trigger: null })).toBe("Run");
});

test("every run status has its sentence", () => {
  const rows: [string, string][] = [
    ["DONE", "Done"],
    ["NOTHING_TO_DO", "Nothing to do"],
    ["PARTIAL", "Kraken refused some orders"],
    ["STOPPED", "Stopped: an order's result was not known"],
    ["UNRESOLVED", "Waited for an earlier order"],
    ["KRAKEN_UNAVAILABLE", "Kraken didn't answer"],
    ["ERROR", "Failed"],
    ["PROPOSED", "Proposal ready"],
    ["SUPERSEDED", "The plan changed; nothing was sent"],
    ["RUNNING", "Running"],
    ["SOMETHING_NEW", "SOMETHING_NEW"],
  ];
  for (const [status, text] of rows) expect(runStatus(status)).toBe(text);
});

test("messages are the non-empty lines of the log", () => {
  expect(messagesOf(null)).toEqual([]);
  expect(messagesOf("a\n\nb")).toEqual(["a", "b"]);
  expect(messagesOf("")).toEqual([]);
});

test("an order status says what happened to it", () => {
  expect(orderStatus({ status: "FILLED", error: null })).toBe("Filled");
  expect(orderStatus({ status: "PENDING", error: null })).toBe(
    "Result not known yet",
  );
  expect(orderStatus({ status: "FAILED", error: "EOrder:Insufficient" })).toBe(
    "Refused by Kraken: EOrder:Insufficient",
  );
  expect(orderStatus({ status: "FAILED", error: null })).toBe(
    "Not found on Kraken",
  );
  expect(orderStatus({ status: "WEIRD", error: null })).toBe("WEIRD");
});

test("an order line names the side, the asset and the requested amount", () => {
  const order = {
    side: "buy",
    asset: "BTC",
    requested_fiat: "50",
  } as components["schemas"]["OrderOut"];
  expect(orderLine(order, "EUR")).toBe("Buy BTC for €50.00");
});
