import type { components } from "@/api/schema";
import { compare, subtract, sum } from "@/lib/decimal";

type Portfolio = components["schemas"]["PortfolioOut"];
type ProposalLeg = components["schemas"]["ProposalLegOut"];

export type Totals = { managed: string; unmanaged: string; total: string };

// total_value already counts the managed assets and the cash; the unmanaged
// holdings add their value when they have one (locked ones never do).
export function accountTotals(portfolio: Portfolio): Totals {
  const managed = portfolio.total_value;
  const unmanaged = sum(
    portfolio.holdings.flatMap((h) =>
      !h.managed && h.value !== null ? [h.value] : [],
    ),
  );
  return { managed, unmanaged, total: sum([managed, unmanaged]) };
}

export type AllocationRow = {
  kind: "asset" | "cash";
  asset: string;
  weight: string | null;
  target: string | null;
  drift: string | null;
  drifted: boolean;
};

export function drift(weight: string, target: string): string {
  return subtract(weight, target);
}

// The engine acts on a drift that is not zero and at least min_drift_pct.
export function isDrifted(driftValue: string, minDrift: string): boolean {
  return (
    compare(driftValue, "0") !== 0 &&
    compare(driftValue.replace(/^-/, ""), minDrift) >= 0
  );
}

function driftOf(weight: string | null, target: string | null): string | null {
  return weight === null || target === null ? null : drift(weight, target);
}

export function allocationRows(
  portfolio: Portfolio,
  minDrift: string,
): AllocationRow[] {
  const assets: AllocationRow[] = portfolio.holdings
    .filter((h) => h.managed)
    .map((h) => {
      const d = driftOf(h.weight_pct, h.target_pct);
      return {
        kind: "asset",
        asset: h.asset,
        weight: h.weight_pct,
        target: h.target_pct,
        drift: d,
        drifted: d !== null && isDrifted(d, minDrift),
      };
    });
  const cash: AllocationRow = {
    kind: "cash",
    asset: "Cash",
    weight: portfolio.cash_weight_pct,
    target: portfolio.cash_target_pct,
    drift: driftOf(portfolio.cash_weight_pct, portfolio.cash_target_pct),
    drifted: false,
  };
  return [...assets, cash];
}

export function formatDrift(driftValue: string): string {
  const sign = compare(driftValue, "0") > 0 ? "+" : "";
  return `${sign}${driftValue} pts`;
}

export function proposalTotals(legs: ProposalLeg[]): {
  orders: number;
  skipped: number;
  total: string;
} {
  const orders = legs.filter((leg) => leg.note === null);
  return {
    orders: orders.length,
    skipped: legs.length - orders.length,
    total: sum(orders.map((leg) => leg.amount_fiat)),
  };
}
