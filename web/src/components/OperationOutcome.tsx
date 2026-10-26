import type { ReactNode } from "react";
import { operationError } from "@/api/client";
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
  refreshError,
  children,
}: {
  result: { status: string; legs: Leg[]; messages: string[] };
  fiat: string;
  refreshError: unknown;
  children?: ReactNode;
}) {
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
          refreshError == null
            ? null
            : `The new balances could not be read. ${operationError(refreshError)}`
        }
      />
    </>
  );
}
