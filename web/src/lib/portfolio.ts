import Big from "big.js";

import { subtract, sum } from "@/lib/decimal";

export type PricedHolding = {
  asset: string;
  value: string | null;
  locked: boolean;
};

// Spec §5.2: each priced, unlocked holding's share of (cash + those values),
// rounded down to one decimal so the weights never sum above 100.
export function prefillWeights(
  cash: string,
  holdings: PricedHolding[],
): Map<string, string> {
  const priced = holdings.filter(
    (h): h is PricedHolding & { value: string } =>
      !h.locked && h.value !== null,
  );
  const total = Big(sum([cash, ...priced.map((h) => h.value)]));
  const weights = new Map<string, string>();
  for (const h of priced) {
    const weight = total.eq(0)
      ? Big(0)
      : Big(h.value).times(100).div(total).round(1, Big.roundDown);
    weights.set(h.asset, weight.toFixed());
  }
  return weights;
}

export function cashTarget(targets: string[]): string {
  return subtract("100", sum(targets));
}

// Decision 5: deletes first, then puts from the largest decrease to the
// largest increase, so the platform's "sum <= 100" check never fails midway.
export function saveOrder(
  stored: Map<string, string>,
  wanted: Map<string, string>,
): { deletes: string[]; puts: { asset: string; target: string }[] } {
  const deletes = [...stored.keys()].filter((asset) => !wanted.has(asset));
  // A target that is already stored as it is needs no write.
  const puts = [...wanted]
    .map(([asset, target]) => ({
      asset,
      target,
      change: Big(target).minus(stored.get(asset) ?? "0"),
    }))
    .filter(({ asset, change }) => !stored.has(asset) || !change.eq(0));
  puts.sort((a, b) => a.change.cmp(b.change) || a.asset.localeCompare(b.asset));
  return {
    deletes,
    puts: puts.map(({ asset, target }) => ({ asset, target })),
  };
}
