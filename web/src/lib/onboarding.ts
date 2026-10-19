export const ONBOARDING_STEPS = [
  "key",
  "portfolio",
  "automation",
  "summary",
] as const;
export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

export function onboardingStep(state: {
  keyRegistered: boolean;
  fiat: string | null;
  assetCount: number;
}): OnboardingStep {
  if (!state.keyRegistered) return "key";
  if (state.fiat === null || state.assetCount === 0) return "portfolio";
  return "automation";
}

// "automation" also reaches "summary": the summary only reads what the
// automation step has set, so a user who got that far may go on.
export function reachableSteps(first: OnboardingStep): OnboardingStep[] {
  const reachable = ONBOARDING_STEPS.slice(
    0,
    ONBOARDING_STEPS.indexOf(first) + 1,
  );
  return first === "automation" ? [...reachable, "summary"] : reachable;
}
