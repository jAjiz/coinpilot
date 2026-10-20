import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { invalidateAccount } from "@/api/queries";
import type { OnboardingStep } from "@/lib/onboarding";

// The gate reads the cached onboarding state: it must be read again before
// navigating, or the gate still sees the old step and sends the user back.
export function useAdvance(): (to: OnboardingStep | "/") => Promise<void> {
  const client = useQueryClient();
  const navigate = useNavigate();
  return async (to) => {
    await invalidateAccount(client);
    await navigate(to === "/" ? "/" : `/onboarding/${to}`);
  };
}
