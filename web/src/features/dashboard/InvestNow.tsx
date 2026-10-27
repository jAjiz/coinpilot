import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, operationError, unwrap } from "@/api/client";
import {
  historyChanged,
  investKey,
  isLostAnswer,
  refreshAfter,
  refreshAfterKey,
  useHeldOperation,
} from "@/api/operations";
import { useConfig } from "@/api/queries";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { LegList } from "@/components/LegList";
import { LostAnswer, OperationOutcome } from "@/components/OperationOutcome";
import { Button } from "@/components/ui/button";
import { useOnline } from "@/features/shell/useOnline";
import { formatMoney, sum } from "@/lib/decimal";
import { sentAnything } from "@/lib/operations";

type InvestOut = components["schemas"]["InvestOut"];
type Step = { kind: "idle" } | { kind: "preview"; result: InvestOut };

export function InvestNow() {
  const client = useQueryClient();
  const config = useConfig();
  const online = useOnline();
  const [step, setStep] = useState<Step>({ kind: "idle" });
  // The confirmed invest, held by the cache: it outlives this screen. Its
  // variables are the preview that was confirmed.
  const held = useHeldOperation<InvestOut, InvestOut>(investKey);
  const refreshHeld = useHeldOperation(refreshAfterKey);
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
  // Its callbacks run whether or not this screen is still mounted.
  const confirm = useMutation<InvestOut, unknown, InvestOut>({
    mutationKey: investKey,
    mutationFn: () => unwrap(api.POST("/api/invest")),
    onSuccess: (result) => {
      if (sentAnything(result.legs)) refreshAfter(client);
    },
    onSettled: () => {
      sending.current = false;
      historyChanged(client);
    },
  });

  const fiat = config.data?.fiat;
  if (fiat === undefined) return null;

  function leave() {
    preview.reset();
    confirm.reset();
    held.release();
    // A failed read of the balances belongs to the outcome being left.
    refreshHeld.release();
    setStep({ kind: "idle" });
  }

  function startPreview() {
    if (sending.current) return;
    sending.current = true;
    held.release();
    preview.mutate();
  }

  function send(result: InvestOut) {
    if (sending.current) return;
    sending.current = true;
    held.release();
    confirm.mutate(result);
  }

  // A held confirmation decides the step; without one, this screen's own.
  const lost = held.state === "error" && isLostAnswer(held.error);
  const outcome = held.state === "success" ? held.data : undefined;
  const previewed =
    held.state === "idle"
      ? step.kind === "preview"
        ? step.result
        : null
      : (held.variables ?? null);

  // The step that failed stays on screen; its error is the one shown.
  let error: string | null = null;
  if (held.state === "error" && !lost) error = operationError(held.error);
  else if (previewed === null && preview.isError) {
    error = operationError(preview.error);
  }

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Invest now</h2>
      {outcome !== undefined ? (
        <OperationOutcome result={outcome} fiat={fiat}>
          <Button variant="outline" onClick={leave}>
            Close
          </Button>
        </OperationOutcome>
      ) : previewed !== null ? (
        <PreviewStep
          result={previewed}
          fiat={fiat}
          pending={held.state === "pending"}
          lost={lost}
          online={online}
          onConfirm={() => send(previewed)}
          onClose={leave}
        />
      ) : (
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
      {lost && (
        <LostAnswer>
          <Button variant="outline" onClick={leave}>
            Close
          </Button>
        </LostAnswer>
      )}
      <FormError message={error} />
    </section>
  );
}

function PreviewStep({
  result,
  fiat,
  pending,
  lost,
  online,
  onConfirm,
  onClose,
}: {
  result: InvestOut;
  fiat: string;
  pending: boolean;
  // The confirmed invest may have been sent: nothing to confirm or cancel.
  lost: boolean;
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
            <Button onClick={onConfirm} disabled={pending || lost || !online}>
              {pending ? "Investing…" : `Confirm: invest ${total}`}
            </Button>
            {!lost && (
              <Button variant="outline" onClick={onClose} disabled={pending}>
                Cancel
              </Button>
            )}
          </div>
        </>
      )}
    </>
  );
}
