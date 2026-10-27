import { useState } from "react";
import { describeError } from "@/api/client";
import { useSessionOrders } from "@/api/queries";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/decimal";
import {
  messagesOf,
  orderLine,
  orderStatus,
  runStatus,
  runTitle,
} from "@/lib/history";
import { formatRun } from "@/lib/summary";

type Session = components["schemas"]["EvaluationOut"];

function Orders({ id, fiat }: { id: string; fiat: string | undefined }) {
  const orders = useSessionOrders(id, true);
  // Amounts need the fiat; wait for it rather than format without one.
  if (orders.isPending || fiat === undefined) {
    return <Skeleton className="h-10 w-full" />;
  }
  if (orders.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-2">
        <p>{describeError(orders.error)}</p>
        <Button onClick={() => orders.refetch()}>Try again</Button>
      </div>
    );
  }
  if (orders.data.length === 0) {
    return <p>No orders are linked to this run.</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {orders.data.map((o) => (
        <li key={o.cl_ord_id}>
          <p>{orderLine(o, fiat)}</p>
          <p className="text-sm text-muted-foreground">{orderStatus(o)}</p>
          {o.status === "FILLED" && o.cost !== null && o.fee !== null && (
            <p className="text-sm text-muted-foreground">
              Cost {formatMoney(o.cost, fiat)} · fee {formatMoney(o.fee, fiat)}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function SessionRow({
  session,
  fiat,
}: {
  session: Session;
  fiat: string | undefined;
}) {
  const [open, setOpen] = useState(false);
  const messages = messagesOf(session.log_messages);
  return (
    <li className="rounded-md border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-col items-start gap-1 p-3 text-left"
      >
        <span className="text-sm text-muted-foreground">
          {formatRun(session.started_at)}
        </span>
        <span className="font-medium">{runTitle(session)}</span>
        <span className="text-sm">{runStatus(session.status)}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t p-3">
          {messages.length > 0 && (
            <ul className="flex flex-col gap-1 text-sm">
              {messages.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          )}
          <Orders id={session.id} fiat={fiat} />
        </div>
      )}
    </li>
  );
}
