import { describeError } from "@/api/client";
import { Button } from "@/components/ui/button";

export function LoadFailed({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="mx-auto flex min-h-dvh max-w-md flex-col items-start justify-center gap-4 p-6"
    >
      <p>{describeError(error)}</p>
      <Button onClick={onRetry}>Try again</Button>
    </div>
  );
}
