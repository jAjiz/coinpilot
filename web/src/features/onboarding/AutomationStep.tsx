import { useState } from "react";
import { useConfig } from "@/api/queries";
import { localDate } from "@/lib/cadence";
import { AutomationForm } from "./AutomationForm";
import { wizardValues } from "./automationValues";
import { useAdvance } from "./useAdvance";
import { StepFailed, StepSkeleton, WizardLayout } from "./WizardLayout";

export function AutomationStep() {
  const config = useConfig();
  const advance = useAdvance();
  const [today] = useState(() => localDate(new Date()));

  return (
    <WizardLayout step="automation" title="Automation">
      {config.isPending ? (
        <StepSkeleton />
      ) : config.isError ? (
        <StepFailed
          error={config.error}
          onRetry={() => void config.refetch()}
        />
      ) : config.data === null ? (
        <p>Choose a currency in the portfolio step first.</p>
      ) : (
        <>
          <p>
            When CoinPilot acts on its own. A run happens between 12:00 and
            13:00 your time.
          </p>
          <AutomationForm
            config={config.data}
            initial={wizardValues(config.data, today)}
            onSaved={() => advance("summary")}
          />
        </>
      )}
    </WizardLayout>
  );
}
