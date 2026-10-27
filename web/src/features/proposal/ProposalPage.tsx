import { useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import {
  ApiError,
  api,
  describeError,
  operationError,
  unwrap,
} from "@/api/client";
import {
  proposalKey,
  useProposal,
  useRefreshPortfolio,
  type Proposal,
} from "@/api/queries";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { OperationOutcome } from "@/components/OperationOutcome";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { proposalTotals } from "@/lib/account";
import { formatMoney } from "@/lib/decimal";
import { countOrders, legLine, sentAnything } from "@/lib/operations";
import { formatRun } from "@/lib/summary";

type RebalanceOut = components["schemas"]["RebalanceOut"];
type Outcome = { result: RebalanceOut; fiat: string };

// A 409 whose body carries the live proposal (null when there is none): the
// version approved was not the live one, or the plan changed under it.
function superseded(
  error: unknown,
): { proposal: Proposal | null; messages: string[] } | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const body = error.body;
  if (typeof body !== "object" || body === null || !("proposal" in body)) {
    return null;
  }
  const { proposal, messages } = body as {
    proposal: Proposal | null;
    messages?: unknown;
  };
  return {
    proposal,
    messages: Array.isArray(messages)
      ? messages.filter((m): m is string => typeof m === "string")
      : [],
  };
}

function isGone(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function ProposalPage() {
  const proposal = useProposal();
  const client = useQueryClient();
  const navigate = useNavigate();
  const online = useOnline();
  const refresh = useRefreshPortfolio();
  // The version the open confirmation is for; null when it is closed.
  const [confirming, setConfirming] = useState<number | null>(null);
  // Held here, not read from a query: after an approval the proposal is gone,
  // and after a 409 there may be none, but what happened stays on screen.
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [notice, setNotice] = useState<string[] | null>(null);
  // Set synchronously, so a second tap in the same tick cannot send again.
  const sending = useRef(false);
  // Once an approval has been sent, a dismissal must not take the page away
  // from its outcome.
  const approved = useRef(false);

  const dismiss = useMutation({
    mutationFn: async (version: number) => {
      try {
        await unwrap(
          api.DELETE("/api/proposal", { params: { query: { version } } }),
        );
      } catch (error) {
        // Already gone is the outcome that was asked for.
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: proposalKey });
      if (!approved.current) void navigate("/");
    },
    // The same answer as an approval's: the live proposal, to be read again.
    onError: (error) => {
      const changed = superseded(error);
      if (changed !== null) {
        client.setQueryData(proposalKey, changed.proposal);
        setConfirming(null);
        setNotice(changed.messages);
      }
    },
  });

  const approve = useMutation({
    mutationFn: ({ version }: { version: number; fiat: string }) =>
      unwrap(api.POST("/api/proposal/approve", { body: { version } })),
    onSuccess: (result, { fiat }) => {
      setOutcome({ result, fiat });
      setConfirming(null);
      void client.invalidateQueries({ queryKey: proposalKey });
      if (sentAnything(result.legs)) refresh.mutate();
    },
    onError: (error) => {
      approved.current = false;
      const changed = superseded(error);
      if (changed !== null) {
        client.setQueryData(proposalKey, changed.proposal);
        setConfirming(null);
        setNotice(changed.messages);
      } else if (isGone(error)) {
        client.setQueryData(proposalKey, null);
        setConfirming(null);
      }
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  // A refetch that brings another version, or none, closes the confirmation:
  // what it asked about is no longer what Confirm would approve.
  const live = proposal.data;
  if (
    confirming !== null &&
    !approve.isPending &&
    live !== undefined &&
    (live === null || live.version !== confirming)
  ) {
    setConfirming(null);
    setNotice([]);
  }

  function open(version: number) {
    setNotice(null);
    approve.reset();
    setConfirming(version);
  }

  function cancel() {
    approve.reset();
    setConfirming(null);
  }

  function send(version: number, fiat: string) {
    if (sending.current || dismiss.isPending) return;
    sending.current = true;
    approved.current = true;
    approve.mutate({ version, fiat });
  }

  function withdraw(version: number) {
    setNotice(null);
    dismiss.mutate(version);
  }

  const heading: ReactNode = (
    <>
      <h1 className="text-xl font-semibold">Proposal</h1>
      {notice !== null && (
        <div className="flex flex-col gap-1 self-stretch rounded-md border p-3">
          <p className="font-medium">The proposal changed; review it again.</p>
          {notice.map((m) => (
            <p key={m}>{m}</p>
          ))}
        </div>
      )}
    </>
  );

  if (outcome !== null) {
    return (
      <div className="flex flex-col items-start gap-3">
        {heading}
        <OperationOutcome
          result={outcome.result}
          fiat={outcome.fiat}
          refreshError={refresh.error}
        >
          <Link to="/" className="font-medium underline">
            Back to Home
          </Link>
        </OperationOutcome>
      </div>
    );
  }

  if (proposal.isError && proposal.data === undefined) {
    return (
      <div className="flex flex-col items-start gap-3">
        {heading}
        <p role="alert">{describeError(proposal.error)}</p>
        <Button onClick={() => void proposal.refetch()}>Try again</Button>
      </div>
    );
  }
  if (proposal.data === undefined) {
    return (
      <div className="flex flex-col gap-3">
        {heading}
        <div role="status" aria-label="Loading" className="flex flex-col gap-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
        </div>
      </div>
    );
  }
  if (proposal.data === null) {
    // While a dismissal navigates away the query is briefly empty: say nothing
    // different, the page is about to change.
    return (
      <div className="flex flex-col items-start gap-3">
        {heading}
        <p>There is no proposal to review.</p>
        <Link to="/" className="font-medium underline">
          Back to Home
        </Link>
      </div>
    );
  }

  const data = proposal.data;
  const totals = proposalTotals(data.legs);
  const orders = data.legs.filter((leg) => leg.note === null);
  const skipped = data.legs.filter((leg) => leg.note !== null);
  const trigger =
    data.trigger === "SCHEDULED" ? "by your schedule" : "on request";
  // A 409 with a proposal and a 404 are answered by the page itself.
  const approveError =
    approve.isError &&
    superseded(approve.error) === null &&
    !isGone(approve.error)
      ? operationError(approve.error)
      : null;

  // A 409 with a proposal is answered by the page itself.
  const dismissError =
    dismiss.isError && superseded(dismiss.error) === null
      ? operationError(dismiss.error)
      : null;

  return (
    <div className="flex flex-col gap-6">
      {heading}
      <p className="text-sm text-muted-foreground">
        Proposed {formatRun(data.updated_at)}, {trigger}
      </p>

      <section className="flex flex-col gap-2">
        <h2 className="font-semibold">Orders</h2>
        {orders.length === 0 ? (
          <p>
            Every order is below Kraken&apos;s minimum, so nothing can be sent.
          </p>
        ) : (
          <>
            <ul className="flex flex-col gap-1">
              {orders.map((leg) => (
                <li key={`${leg.side}-${leg.asset}`}>
                  {legLine(leg, data.fiat)}
                </li>
              ))}
            </ul>
            <p className="font-medium">
              Total {formatMoney(totals.total, data.fiat)}
            </p>
            {confirming !== null ? (
              <div className="flex flex-col items-start gap-3">
                <p>
                  Send {countOrders(orders.length)} for{" "}
                  {formatMoney(totals.total, data.fiat)}?
                </p>
                <div className="flex gap-2">
                  <Button
                    onClick={() => send(confirming, data.fiat)}
                    disabled={approve.isPending || dismiss.isPending || !online}
                  >
                    {approve.isPending ? "Sending…" : "Confirm"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={cancel}
                    disabled={approve.isPending}
                  >
                    Cancel
                  </Button>
                </div>
                <FormError message={approveError} />
              </div>
            ) : (
              <Button
                className="self-start"
                onClick={() => open(data.version)}
                disabled={dismiss.isPending || !online}
              >
                Approve
              </Button>
            )}
          </>
        )}
      </section>

      {skipped.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="font-semibold">Skipped</h2>
          <ul className="flex flex-col gap-1">
            {skipped.map((leg) => (
              <li key={`${leg.side}-${leg.asset}`}>
                {legLine(leg, data.fiat)}: {leg.note}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-col items-start gap-3">
        <FormError message={dismissError} />
        <Button
          variant="outline"
          onClick={() => withdraw(data.version)}
          disabled={
            confirming !== null ||
            dismiss.isPending ||
            approve.isPending ||
            !online
          }
        >
          {dismiss.isPending ? "Dismissing…" : "Dismiss"}
        </Button>
      </section>
    </div>
  );
}
