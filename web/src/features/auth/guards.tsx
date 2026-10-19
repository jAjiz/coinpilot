import type { ReactElement } from "react";
import { Navigate, Outlet, useParams } from "react-router";
import { FullPageSkeleton } from "@/components/FullPageSkeleton";
import { LoadFailed } from "@/components/LoadFailed";
import { reachableSteps, type OnboardingStep } from "@/lib/onboarding";
import { useMe, useOnboarding, type Onboarding } from "./session";

export function RequireSession() {
  const me = useMe();
  if (me.isPending) return <FullPageSkeleton />;
  if (me.isError) return <LoadFailed error={me.error} onRetry={me.refetch} />;
  if (me.data === null) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function WithOnboarding({
  children,
}: {
  children: (state: Onboarding) => ReactElement;
}) {
  const onboarding = useOnboarding();
  if (onboarding.isError) {
    return <LoadFailed error={onboarding.error} onRetry={onboarding.refetch} />;
  }
  if (!onboarding.data) return <FullPageSkeleton />;
  return children(onboarding.data);
}

export function RequireOnboarded() {
  return (
    <WithOnboarding>
      {(state) =>
        state.onboarded ? (
          <Outlet />
        ) : (
          <Navigate to={`/onboarding/${state.step}`} replace />
        )
      }
    </WithOnboarding>
  );
}

export function OnboardingGate() {
  const { step } = useParams<{ step?: string }>();
  return (
    <WithOnboarding>
      {(state) => {
        if (state.onboarded) return <Navigate to="/" replace />;
        if (!reachableSteps(state.step).includes(step as OnboardingStep)) {
          return <Navigate to={`/onboarding/${state.step}`} replace />;
        }
        return <Outlet />;
      }}
    </WithOnboarding>
  );
}
