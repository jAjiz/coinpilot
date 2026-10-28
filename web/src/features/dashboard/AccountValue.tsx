import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { describeError, operationError } from "@/api/client";
import {
  claimOpenRead,
  usePortfolio,
  useRefreshPortfolio,
  type Portfolio,
} from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { accountTotals } from "@/lib/account";
import { formatMoney } from "@/lib/decimal";
import { formatRun } from "@/lib/summary";

// A reading older than this is read again when the application comes back to
// the foreground: a PWA on a phone resumes rather than reloads.
const STALE_AFTER_MS = 5 * 60_000;

function useReadOnOpen(
  snapshot: Portfolio | null | undefined,
  read: () => void,
  canRead: boolean,
) {
  const client = useQueryClient();
  const latest = useRef({ snapshot, read, canRead });
  useEffect(() => {
    latest.current = { snapshot, read, canRead };
  });

  // After the stored reading has loaded, so that its answer cannot land on top
  // of the fresh one.
  const loaded = snapshot !== undefined;
  useEffect(() => {
    if (!loaded || !canRead || !claimOpenRead(client)) return;
    latest.current.read();
  }, [loaded, canRead, client]);

  useEffect(() => {
    function onVisible() {
      const { snapshot, read, canRead } = latest.current;
      if (document.visibilityState !== "visible" || !canRead) return;
      if (
        snapshot === undefined ||
        (snapshot !== null &&
          Date.now() - new Date(snapshot.as_of).getTime() < STALE_AFTER_MS)
      ) {
        return;
      }
      read();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
}

export function AccountValue() {
  const portfolio = usePortfolio();
  const refresh = useRefreshPortfolio();
  const online = useOnline();
  const { mutate } = refresh;
  useReadOnOpen(portfolio.data, () => mutate(), online && !refresh.isPending);

  if (portfolio.isError && portfolio.data === undefined) {
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
