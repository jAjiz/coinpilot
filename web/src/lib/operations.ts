import { formatMoney } from "@/lib/decimal";

type Leg = { side: string; asset: string; amount_fiat: string };

export function legLine(leg: Leg, fiat: string): string {
  const side =
    leg.side.charAt(0).toUpperCase() + leg.side.slice(1).toLowerCase();
  return `${side} ${leg.asset} for ${formatMoney(leg.amount_fiat, fiat)}`;
}

function because(text: string, reason: string | null): string {
  return reason === null ? text : `${text}: ${reason}`;
}

export function legStatus(leg: {
  status: string;
  error: string | null;
  note: string | null;
}): string {
  switch (leg.status) {
    case "VALIDATED":
      return "Kraken accepts it";
    case "REJECTED":
      return because("Kraken refuses it", leg.error);
    case "SKIPPED":
      return because("Skipped", leg.note);
    case "UNCHECKED":
      return "Not checked by Kraken";
    case "FILLED":
      return "Filled";
    case "FAILED":
      return because("Failed", leg.error);
    case "PENDING":
      return "Sent; the result is not known yet";
    default:
      return leg.status;
  }
}

export function outcomeSentence(status: string): string {
  switch (status) {
    case "DONE":
      return "Every order was filled.";
    case "PARTIAL":
      return "Kraken refused some orders; the others were filled.";
    case "STOPPED":
      return "The result of an order is not known yet. CoinPilot checks it before the next operation.";
    case "ERROR":
      return "The operation failed. Nothing more was sent.";
    case "NOTHING_TO_DO":
      return "Nothing to do.";
    case "PROPOSED":
      return "A rebalance is waiting for your approval.";
    default:
      return status;
  }
}

export function countOrders(n: number): string {
  return n === 1 ? "1 order" : `${n} orders`;
}

export function sentAnything(legs: { status: string }[]): boolean {
  return legs.some(
    (leg) => leg.status === "FILLED" || leg.status === "PENDING",
  );
}
