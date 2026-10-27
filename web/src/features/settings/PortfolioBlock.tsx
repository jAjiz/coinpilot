import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { describeError } from "@/api/client";
import { invalidateAccount, useAssets, useConfig } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PortfolioForm } from "@/features/onboarding/PortfolioForm";
import { formatPercent } from "@/lib/decimal";

export function PortfolioBlock() {
  const client = useQueryClient();
  const config = useConfig();
  const assets = useAssets();
  const [editing, setEditing] = useState(false);

  if (config.data === null) return null;
  // Once the data exists it stays, whatever a later refetch does: an open
  // form holds the user's edits.
  if (config.data === undefined || assets.data === undefined) {
    if (!config.isError && !assets.isError) {
      return <Skeleton className="h-24 w-full" />;
    }
    return (
      <section className="flex flex-col items-start gap-3">
        <h2 className="text-lg font-semibold">Portfolio</h2>
        <FormError message={describeError(config.error ?? assets.error)} />
        <Button
          onClick={() => {
            void config.refetch();
            void assets.refetch();
          }}
        >
          Try again
        </Button>
      </section>
    );
  }
  const { fiat } = config.data;

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Portfolio</h2>
      {editing ? (
        <>
          <PortfolioForm
            fiat={fiat}
            onSaved={async () => {
              await invalidateAccount(client);
              setEditing(false);
            }}
          />
          <Button variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </>
      ) : (
        <>
          {assets.data.assets.length === 0 ? (
            <p>No asset is managed yet.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {assets.data.assets.map((a) => (
                <li key={a.asset}>
                  {a.asset} {formatPercent(a.target_pct)}
                </li>
              ))}
              <li>Cash {formatPercent(assets.data.cash_target_pct)}</li>
            </ul>
          )}
          <p>Currency: {fiat}. It cannot be changed.</p>
          <Button variant="outline" onClick={() => setEditing(true)}>
            Edit targets
          </Button>
        </>
      )}
    </section>
  );
}
