import type { components } from "@/api/schema";
import { legLine } from "@/lib/operations";

type Session = components["schemas"]["EvaluationOut"];
type Order = components["schemas"]["OrderOut"];

const OPERATIONS: Record<string, string> = {
  INVEST: "Invest",
  PROPOSE: "Rebalance check",
  APPROVE: "Approved rebalance",
  REBALANCE: "Automatic rebalance",
};

const TRIGGERS: Record<string, string> = {
  API: "by you",
  SCHEDULER: "scheduled",
};

export function runTitle(s: Pick<Session, "operation" | "trigger">): string {
  const operation =
    s.operation === null ? "Run" : (OPERATIONS[s.operation] ?? s.operation);
  if (s.trigger === null) return operation;
  return `${operation} · ${TRIGGERS[s.trigger] ?? s.trigger}`;
}

export function runStatus(status: string): string {
  switch (status) {
    case "DONE":
      return "Done";
    case "NOTHING_TO_DO":
      return "Nothing to do";
    case "PARTIAL":
      return "Kraken refused some orders";
    case "STOPPED":
      return "Stopped: an order's result was not known";
    case "UNRESOLVED":
      return "Waited for an earlier order";
    case "KRAKEN_UNAVAILABLE":
      return "Kraken didn't answer";
    case "ERROR":
      return "Failed";
    case "PROPOSED":
      return "Proposal ready";
    case "SUPERSEDED":
      return "The plan changed; nothing was sent";
    case "RUNNING":
      return "Running";
    default:
      return status;
  }
}

export function messagesOf(log: string | null): string[] {
  return log === null ? [] : log.split("\n").filter((line) => line !== "");
}

export function orderStatus(o: Pick<Order, "status" | "error">): string {
  switch (o.status) {
    case "FILLED":
      return "Filled";
    case "PENDING":
      return "Result not known yet";
    case "FAILED":
      return o.error === null
        ? "Not found on Kraken"
        : `Refused by Kraken: ${o.error}`;
    default:
      return o.status;
  }
}

export function orderLine(o: Order, fiat: string): string {
  return legLine(
    { side: o.side, asset: o.asset, amount_fiat: o.requested_fiat },
    fiat,
  );
}
