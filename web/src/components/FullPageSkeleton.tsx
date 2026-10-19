import { Skeleton } from "@/components/ui/skeleton";

export function FullPageSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-6"
    >
      <Skeleton className="h-8 w-1/2" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}
