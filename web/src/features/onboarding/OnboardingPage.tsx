import { useParams } from "react-router";
import type { OnboardingStep } from "@/lib/onboarding";
import { AutomationStep } from "./AutomationStep";
import { KeyStep } from "./KeyStep";
import { PortfolioStep } from "./PortfolioStep";
import { WizardLayout } from "./WizardLayout";

const HEADINGS: Record<OnboardingStep, string> = {
  key: "Kraken key",
  portfolio: "Portfolio",
  automation: "Automation",
  summary: "Summary",
};

export function OnboardingPage() {
  const step = useParams<{ step: OnboardingStep }>().step!;
  if (step === "key") return <KeyStep />;
  if (step === "portfolio") return <PortfolioStep />;
  if (step === "automation") return <AutomationStep />;
  return (
    <WizardLayout step={step} title={HEADINGS[step]}>
      <p>This step is not built yet.</p>
    </WizardLayout>
  );
}
