import { useState } from "react";
import { api, describeError, unwrap } from "@/api/client";
import { useConfig, type Config } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { useOnline } from "@/features/shell/useOnline";
import { cadenceOf, localDate, readInvest, readRebalance } from "@/lib/cadence";
import { formatRun, startsLater, summarize } from "@/lib/summary";
import { useAdvance } from "./useAdvance";
import { StepFailed, StepSkeleton, WizardLayout } from "./WizardLayout";

const PASSED = "The start date has passed, so the first run is the next one.";

function Summary({ config, today }: { config: Config; today: string }) {
  const online = useOnline();
  const advance = useAdvance();
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const invest = readInvest(cadenceOf(config, "invest"), today);
  const rebalance = readRebalance(cadenceOf(config, "rebalance"));
  const sentences = summarize({
    fiat: config.fiat,
    invest,
    rebalance,
    invest_cash_enabled: config.invest_cash_enabled,
    cash_rebalance_enabled: config.cash_rebalance_enabled,
    auto_rebalance_enabled: config.auto_rebalance_enabled,
    min_drift_pct: config.min_drift_pct,
    min_order_fiat: config.min_order_fiat,
  });

  async function start() {
    setFailure(null);
    setSending(true);
    try {
      await unwrap(api.PATCH("/api/config", { body: { onboarded: true } }));
      // Stays disabled while the app advances: a second click would send again.
      await advance("/");
    } catch (error) {
      setFailure(describeError(error));
      setSending(false);
    }
  }

  return (
    <>
      <p>This is what CoinPilot will do. Nothing is traded until then.</p>
      {sentences.map((sentence) => (
        <p key={sentence}>{sentence}</p>
      ))}
      {config.next_invest_at !== null && (
        <>
          <p>First investment: {formatRun(config.next_invest_at)}</p>
          {startsLater(invest, config.next_invest_at) && (
            <p className="text-sm text-muted-foreground">{PASSED}</p>
          )}
        </>
      )}
      {config.next_rebalance_at !== null && (
        <>
          <p>First rebalance check: {formatRun(config.next_rebalance_at)}</p>
          {startsLater(rebalance, config.next_rebalance_at) && (
            <p className="text-sm text-muted-foreground">{PASSED}</p>
          )}
        </>
      )}
      <FormError message={failure} />
      <Button disabled={sending || !online} onClick={() => void start()}>
        Start
      </Button>
    </>
  );
}

export function SummaryStep() {
  const config = useConfig();
  const [today] = useState(() => localDate(new Date()));

  return (
    <WizardLayout step="summary" title="Summary">
      {config.isPending ? (
        <StepSkeleton />
      ) : config.isError ? (
        <StepFailed
          error={config.error}
          onRetry={() => void config.refetch()}
        />
      ) : config.data === null ? (
        <p>Choose a currency in the portfolio step first.</p>
      ) : config.data.rebalance_cadence_mode === "MIN" ? (
        // The automation step always saves an interval: MIN means it was not saved.
        <p>Save the automation step first.</p>
      ) : (
        <Summary config={config.data} today={today} />
      )}
    </WizardLayout>
  );
}
