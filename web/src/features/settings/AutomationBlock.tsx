import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { describeError } from "@/api/client";
import { configKey, useConfig } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AutomationForm } from "@/features/onboarding/AutomationForm";
import { settingsValues } from "@/features/onboarding/automationValues";
import { localDate, readInvest, readRebalance, cadenceOf } from "@/lib/cadence";
import { formatRun, summarize } from "@/lib/summary";

export function AutomationBlock() {
  const client = useQueryClient();
  const config = useConfig();
  const [editing, setEditing] = useState(false);
  const [today] = useState(() => localDate(new Date()));

  if (config.data === null) return null;
  // Once the data exists it stays, whatever a later refetch does.
  if (config.data === undefined && config.isError) {
    return (
      <section className="flex flex-col items-start gap-3">
        <h2 className="text-lg font-semibold">Automation</h2>
        <FormError message={describeError(config.error)} />
        <Button onClick={() => void config.refetch()}>Try again</Button>
      </section>
    );
  }
  if (config.data === undefined) {
    return <Skeleton className="h-24 w-full" />;
  }
  const data = config.data;

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Automation</h2>
      {editing ? (
        <>
          <AutomationForm
            config={data}
            initial={settingsValues(data, today)}
            onSaved={async () => {
              // The refetch carries the moved next runs.
              await client.invalidateQueries({ queryKey: configKey });
              setEditing(false);
            }}
          />
          <Button variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </>
      ) : (
        <>
          {summarize({
            fiat: data.fiat,
            invest: readInvest(cadenceOf(data, "invest"), today),
            rebalance: readRebalance(cadenceOf(data, "rebalance")),
            invest_cash_enabled: data.invest_cash_enabled,
            cash_rebalance_enabled: data.cash_rebalance_enabled,
            auto_rebalance_enabled: data.auto_rebalance_enabled,
            min_drift_pct: data.min_drift_pct,
            min_order_fiat: data.min_order_fiat,
          }).map((sentence) => (
            <p key={sentence}>{sentence}</p>
          ))}
          {data.next_invest_at !== null && (
            <p>Next invest: {formatRun(data.next_invest_at)}</p>
          )}
          {data.next_rebalance_at !== null && (
            <p>Next rebalance: {formatRun(data.next_rebalance_at)}</p>
          )}
          <Button variant="outline" onClick={() => setEditing(true)}>
            Edit automation
          </Button>
        </>
      )}
    </section>
  );
}
