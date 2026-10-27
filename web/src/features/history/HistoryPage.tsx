import { useConfig, useSessions } from "@/api/queries";
import { LoadFailed } from "@/components/LoadFailed";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { SessionRow } from "./SessionRow";

export function HistoryPage() {
  const sessions = useSessions();
  const config = useConfig();
  const online = useOnline();

  let body;
  if (sessions.isError) {
    body = (
      <LoadFailed error={sessions.error} onRetry={() => sessions.refetch()} />
    );
  } else if (sessions.isPending) {
    body = (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  } else {
    const rows = sessions.data.pages.flat();
    const fiat = config.data?.fiat ?? "";
    body =
      rows.length === 0 ? (
        <p>
          Nothing has happened yet. Runs that invest, rebalance or fail show
          here.
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {rows.map((s) => (
              <SessionRow key={s.id} session={s} fiat={fiat} />
            ))}
          </ul>
          {sessions.hasNextPage && (
            <Button
              variant="outline"
              disabled={sessions.isFetchingNextPage || !online}
              onClick={() => sessions.fetchNextPage()}
            >
              Load more
            </Button>
          )}
        </>
      );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">History</h1>
      {body}
    </div>
  );
}
