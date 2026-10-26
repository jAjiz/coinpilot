import { expect, test } from "vitest";

import {
  accountTotals,
  allocationRows,
  drift,
  formatDrift,
  isDrifted,
  proposalTotals,
} from "@/lib/account";
import type { components } from "@/api/schema";

type Portfolio = components["schemas"]["PortfolioOut"];
type Holding = components["schemas"]["HoldingOut"];

function holding(overrides: Partial<Holding> & { asset: string }): Holding {
  return {
    amount: null,
    price: null,
    value: null,
    managed: true,
    locked: false,
    target_pct: null,
    weight_pct: null,
    ...overrides,
  };
}

function portfolio(overrides: Partial<Portfolio> = {}): Portfolio {
  return {
    as_of: "2026-10-26T08:00:00Z",
    fiat: "EUR",
    total_value: "1000",
    cash: "100",
    cash_target_pct: "10",
    cash_weight_pct: "10",
    holdings: [],
    ...overrides,
  };
}

test("managed includes cash, unmanaged is the priced rest", () => {
  const totals = accountTotals(
    portfolio({
      holdings: [
        holding({ asset: "BTC", value: "600" }),
        holding({ asset: "XRP", managed: false, value: "50" }),
        holding({ asset: "DOGE", managed: false, value: null }),
        holding({ asset: "DOT.S", managed: false, locked: true, value: null }),
      ],
    }),
  );
  expect(totals).toEqual({ managed: "1000", unmanaged: "50", total: "1050" });
});

test("rows are the managed assets in the API's order, then cash", () => {
  const rows = allocationRows(
    portfolio({
      holdings: [
        holding({ asset: "BTC", weight_pct: "32.5", target_pct: "30" }),
        holding({ asset: "ETH", weight_pct: "57.5", target_pct: "60" }),
        holding({ asset: "XRP", managed: false }),
      ],
    }),
    "1",
  );
  expect(rows.map((r) => [r.kind, r.asset])).toEqual([
    ["asset", "BTC"],
    ["asset", "ETH"],
    ["cash", "Cash"],
  ]);
  expect(rows.map((r) => r.drift)).toEqual(["2.5", "-2.5", "0"]);
});

test("a drift at the threshold is highlighted, below it is not", () => {
  const p = portfolio({
    holdings: [holding({ asset: "BTC", weight_pct: "32.5", target_pct: "30" })],
  });
  expect(allocationRows(p, "2.5")[0].drifted).toBe(true);
  expect(allocationRows(p, "2.6")[0].drifted).toBe(false);
});

test("no threshold highlights every asset off its target, not one on it", () => {
  expect(isDrifted("0.01", "0")).toBe(true);
  expect(isDrifted("0", "0")).toBe(false);
});

test("cash is never highlighted", () => {
  const rows = allocationRows(
    portfolio({ cash_weight_pct: "0", cash_target_pct: "15" }),
    "1",
  );
  const cash = rows[rows.length - 1];
  expect(cash.drift).toBe("-15");
  expect(cash.drifted).toBe(false);
});

test("an old snapshot and an unpriced asset give no drift", () => {
  const rows = allocationRows(
    portfolio({
      cash_weight_pct: null,
      cash_target_pct: null,
      holdings: [holding({ asset: "SOL", weight_pct: null, target_pct: "5" })],
    }),
    "1",
  );
  expect(rows[0]).toMatchObject({ asset: "SOL", drift: null, drifted: false });
  expect(rows[1]).toMatchObject({
    kind: "cash",
    weight: null,
    drift: null,
    drifted: false,
  });
});

test("drift is told in signed points", () => {
  expect(formatDrift("2.5")).toBe("+2.5 pts");
  expect(formatDrift("-0.25")).toBe("-0.25 pts");
  expect(formatDrift("0")).toBe("0 pts");
  expect(drift("32.5", "30")).toBe("2.5");
});

test("a proposal counts its orders and leaves the skipped out of the total", () => {
  const leg = (
    asset: string,
    side: string,
    amount_fiat: string,
    note: string | null,
  ) => ({
    asset,
    pair: `${asset}/EUR`,
    side,
    amount_fiat,
    minimum_fiat: null,
    note,
  });
  expect(
    proposalTotals([
      leg("BTC", "buy", "50", null),
      leg("ETH", "sell", "20.5", null),
      leg("SOL", "buy", "3", "below kraken's minimum"),
    ]),
  ).toEqual({ orders: 2, skipped: 1, total: "70.5" });
});
