import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, operationError, unwrap } from "@/api/client";
import { useConfig, useRefreshPortfolio } from "@/api/queries";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { LegList } from "@/components/LegList";
import { OperationOutcome } from "@/components/OperationOutcome";
import { Button } from "@/components/ui/button";
import { useOnline } from "@/features/shell/useOnline";
import { formatMoney, sum } from "@/lib/decimal";
import { sentAnything } from "@/lib/operations";

type InvestOut = components["schemas"]["InvestOut"];
type Step =
  | { kind: "idle" }
  | { kind: "preview"; result: InvestOut }
  | { kind: "outcome"; result: InvestOut };

export function InvestNow() {
  const config = useConfig();
  const refresh = useRefreshPortfolio();
  const online = useOnline();
  const [step, setStep] = useState<Step>({ kind: "idle" });
  // Set synchronously, so a second tap in the same tick cannot send again.
  const sending = useRef(false);

  const preview = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/invest", { params: { query: { preview: true } } })),
    onSuccess: (result) => setStep({ kind: "preview", result }),
    onSettled: () => {
      sending.current = false;
    },
  });
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/api/invest")),
    onSuccess: (result) => {
      setStep({ kind: "outcome", result });
      if (sentAnything(result.legs)) refresh.mutate();
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  const fiat = config.data?.fiat;
  if (fiat === undefined) return null;

  function leave() {
    preview.reset();
    confirm.reset();
    // A failed read of the balances belongs to the outcome being left.
    refresh.reset();
    setStep({ kind: "idle" });
  }

  function startPreview() {
    if (sending.current) return;
    sending.current = true;
    confirm.reset();
    preview.mutate();
  }

  function send() {
    if (sending.current) return;
    sending.current = true;
    confirm.mutate();
  }

  // The step that failed stays on screen; its error is the one shown.
  const failure = step.kind === "idle" ? preview : confirm;
  const error = failure.isError ? operationError(failure.error) : null;

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Invest now</h2>
      {step.kind === "idle" && (
        <>
          <p>
            Invest the free {fiat} toward your targets. You see the orders
            before anything is sent.
          </p>
          <Button
            onClick={startPreview}
            disabled={preview.isPending || !online}
          >
            {preview.isPending ? "Asking Kraken…" : "Invest now"}
          </Button>
        </>
      )}
      {step.kind === "preview" && (
        <PreviewStep
          result={step.result}
          fiat={fiat}
          pending={confirm.isPending}
          online={online}
          onConfirm={send}
          onClose={leave}
        />
      )}
      {step.kind === "outcome" && (
        <OperationOutcome
          result={step.result}
          fiat={fiat}
          refreshError={refresh.error}
        >
          <Button variant="outline" onClick={leave}>
            Close
          </Button>
        </OperationOutcome>
      )}
      <FormError message={error} />
    </section>
  );
}

function PreviewStep({
  result,
  fiat,
  pending,
  online,
  onConfirm,
  onClose,
}: {
  result: InvestOut;
  fiat: string;
  pending: boolean;
  online: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  if (result.legs.length === 0) {
    return (
      <>
        <p>Nothing to invest.</p>
        {result.messages.map((m) => (
          <p key={m}>{m}</p>
        ))}
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </>
    );
  }
  // The confirmed invest sends every leg Kraken accepted and every leg it
  // could not check; the total is what will be sent.
  const toSend = result.legs.filter(
    (leg) => leg.status === "VALIDATED" || leg.status === "UNCHECKED",
  );
  const unchecked = toSend.some((leg) => leg.status === "UNCHECKED");
  const total = formatMoney(sum(toSend.map((l) => l.amount_fiat)), fiat);
  return (
    <>
      <LegList legs={result.legs} fiat={fiat} />
      {toSend.length === 0 ? (
        <>
          <p>Kraken would accept none of these orders.</p>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </>
      ) : (
        <>
          <p>Total {total}</p>
          {unchecked && (
            <p>
              Kraken could not check every order; the unchecked ones are sent
              too.
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            Prices move: the orders are computed again when you confirm.
          </p>
          <div className="flex gap-2">
            <Button onClick={onConfirm} disabled={pending || !online}>
              {pending ? "Investing…" : `Confirm: invest ${total}`}
            </Button>
            <Button variant="outline" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
          </div>
        </>
      )}
    </>
  );
}
