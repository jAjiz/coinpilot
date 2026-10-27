import type { ReactNode } from "react";
import { Link } from "react-router";
import { operationError } from "@/api/client";
import { refreshAfterKey, useHeldOperation } from "@/api/operations";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { LegList } from "@/components/LegList";
import { outcomeSentence } from "@/lib/operations";

type Leg = components["schemas"]["LegOut"];

// What an operation that may have sent orders did, and whether the balances
// read after it failed. The caller's own way out goes in `children`.
export function OperationOutcome({
  result,
  fiat,
  children,
}: {
  result: { status: string; legs: Leg[]; messages: string[] };
  fiat: string;
  children?: ReactNode;
}) {
  const refresh = useHeldOperation(refreshAfterKey);
  return (
    <>
      <p>{outcomeSentence(result.status)}</p>
      <LegList legs={result.legs} fiat={fiat} />
      {result.messages.map((m) => (
        <p key={m}>{m}</p>
      ))}
      {children}
      <FormError
        message={
          refresh.state === "error"
            ? `The new balances could not be read. ${operationError(refresh.error)}`
            : null
        }
      />
    </>
  );
}

// A confirmation whose answer never came back may have sent orders: it is not
// an error to retry. The caller's own way out goes in `children`.
export function LostAnswer({ children }: { children?: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 self-stretch rounded-md border p-3"
    >
      <p>
        We don&apos;t know whether the orders were sent: the answer was lost.
        Check History before trying again.
      </p>
      <Link to="/history" className="font-medium underline">
        Open History
      </Link>
      {children}
    </div>
  );
}
