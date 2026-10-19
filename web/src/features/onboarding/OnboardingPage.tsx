import { useParams } from "react-router";
import { OfflineNotice } from "@/features/shell/OfflineNotice";
import type { OnboardingStep } from "@/lib/onboarding";

const HEADINGS: Record<OnboardingStep, string> = {
  key: "Kraken key",
  portfolio: "Portfolio",
  automation: "Automation",
  summary: "Summary",
};

export function OnboardingPage() {
  const { step } = useParams<{ step: OnboardingStep }>();
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col">
      <OfflineNotice />
      <main className="flex-1 p-6">
        <h1 className="text-xl font-semibold">{HEADINGS[step!]}</h1>
        <p>This step is not built yet.</p>
      </main>
    </div>
  );
}
