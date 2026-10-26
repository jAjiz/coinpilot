import { describeError, operationError } from "@/api/client";
import { usePortfolio, useRefreshPortfolio } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { accountTotals } from "@/lib/account";
import { formatMoney } from "@/lib/decimal";
import { formatRun } from "@/lib/summary";

export function AccountValue() {
  const portfolio = usePortfolio();
  const refresh = useRefreshPortfolio();
  const online = useOnline();

  if (portfolio.isError) {
    return (
      <section className="flex flex-col items-start gap-3">
        <p role="alert">{describeError(portfolio.error)}</p>
        <Button onClick={() => void portfolio.refetch()}>Try again</Button>
      </section>
    );
  }
  if (portfolio.data === undefined) {
    return (
      <div role="status" aria-label="Loading" className="flex flex-col gap-3">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
      </div>
    );
  }

  const snapshot = portfolio.data;
  const refreshButton = (
    <Button
      variant="outline"
      onClick={() => refresh.mutate()}
      disabled={refresh.isPending || !online}
    >
      {refresh.isPending ? "Reading Kraken…" : "Refresh"}
    </Button>
  );

  if (snapshot === null) {
    return (
      <section className="flex flex-col items-start gap-3">
        <p>Your account has not been read yet.</p>
        <FormError
          message={refresh.isError ? operationError(refresh.error) : null}
        />
        {refreshButton}
      </section>
    );
  }

  const totals = accountTotals(snapshot);
  const fiat = snapshot.fiat;
  return (
    <section className="flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">Account value</p>
      <p className="text-3xl font-semibold">
        {formatMoney(totals.total, fiat)}
      </p>
      <p>
        Managed {formatMoney(totals.managed, fiat)} · unmanaged{" "}
        {formatMoney(totals.unmanaged, fiat)}
      </p>
      {snapshot.holdings.some((h) => h.locked) && (
        <p className="text-sm text-muted-foreground">
          Locked balances (staked or reserved) are not valued.
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Read {formatRun(snapshot.as_of)}
        </p>
        {refreshButton}
      </div>
      <FormError
        message={refresh.isError ? operationError(refresh.error) : null}
      />
    </section>
  );
}
