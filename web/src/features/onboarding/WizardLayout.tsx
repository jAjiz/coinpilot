import type { ReactNode } from "react";
import { Link } from "react-router";
import { describeError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { OfflineNotice } from "@/features/shell/OfflineNotice";
import { ONBOARDING_STEPS, type OnboardingStep } from "@/lib/onboarding";

export function WizardLayout({
  step,
  title,
  children,
}: {
  step: OnboardingStep;
  title: string;
  children: ReactNode;
}) {
  const index = ONBOARDING_STEPS.indexOf(step);
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col">
      <OfflineNotice />
      <main className="flex flex-1 flex-col gap-4 p-6">
        <p className="text-sm text-muted-foreground">
          Step {index + 1} of {ONBOARDING_STEPS.length}
        </p>
        <h1 className="text-xl font-semibold">{title}</h1>
        {children}
        {index > 0 && (
          <Link
            to={`/onboarding/${ONBOARDING_STEPS[index - 1]}`}
            className="text-sm underline underline-offset-4"
          >
            Back
          </Link>
        )}
      </main>
    </div>
  );
}

export function StepSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-4">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export function StepFailed({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-4">
      <p>{describeError(error)}</p>
      <Button onClick={onRetry}>Try again</Button>
    </div>
  );
}
