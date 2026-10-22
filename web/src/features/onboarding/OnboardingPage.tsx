import { useParams } from "react-router";
import type { OnboardingStep } from "@/lib/onboarding";
import { AutomationStep } from "./AutomationStep";
import { KeyStep } from "./KeyStep";
import { PortfolioStep } from "./PortfolioStep";
import { SummaryStep } from "./SummaryStep";

export function OnboardingPage() {
  const step = useParams<{ step: OnboardingStep }>().step!;
  if (step === "key") return <KeyStep />;
  if (step === "portfolio") return <PortfolioStep />;
  if (step === "automation") return <AutomationStep />;
  return <SummaryStep />;
}
