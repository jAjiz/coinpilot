import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import {
  ApiError,
  api,
  describeError,
  operationError,
  unwrap,
} from "@/api/client";
import { proposalKey, useProposal } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { proposalTotals } from "@/lib/account";
import { formatMoney } from "@/lib/decimal";
import { legLine } from "@/lib/operations";
import { formatRun } from "@/lib/summary";

export function ProposalPage() {
  const proposal = useProposal();
  const client = useQueryClient();
  const navigate = useNavigate();
  const online = useOnline();

  const dismiss = useMutation({
    mutationFn: async () => {
      try {
        await unwrap(api.DELETE("/api/proposal"));
      } catch (error) {
        // Already gone is the outcome that was asked for.
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: proposalKey });
      void navigate("/");
    },
  });

  const heading = <h1 className="text-xl font-semibold">Proposal</h1>;

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
        <FormError
          message={dismiss.isError ? operationError(dismiss.error) : null}
        />
        <Button
          variant="outline"
          onClick={() => dismiss.mutate()}
          disabled={dismiss.isPending || !online}
        >
          {dismiss.isPending ? "Dismissing…" : "Dismiss"}
        </Button>
      </section>
    </div>
  );
}
