import { describeError } from "@/api/client";
import { useConfig, useSessions } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { LoadFailed } from "@/components/LoadFailed";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOnline } from "@/features/shell/useOnline";
import { SessionRow } from "./SessionRow";

export function HistoryPage() {
  const sessions = useSessions();
  const config = useConfig();
  const online = useOnline();

  // A failure replaces the page only while there is nothing to show. Once the
  // runs are read they stay, whatever a later read does.
  let body;
  if (sessions.data === undefined && sessions.isError) {
    body = (
      <LoadFailed error={sessions.error} onRetry={() => sessions.refetch()} />
    );
  } else if (config.data === undefined && config.isError) {
    body = <LoadFailed error={config.error} onRetry={() => config.refetch()} />;
  } else if (sessions.data === undefined) {
    body = (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  } else {
    const rows = sessions.data.pages.flat();
    const fiat = config.data?.fiat;
    const busy = sessions.isFetching || !online;
    body = (
      <>
        {sessions.isRefetchError && (
          <div className="flex flex-col items-start gap-2">
            <FormError message={describeError(sessions.error)} />
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => sessions.refetch()}
            >
              Try again
            </Button>
          </div>
        )}
        {rows.length === 0 ? (
          <p>
            Nothing has happened yet. Runs that invest, rebalance or fail show
            here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {rows.map((s) => (
              <SessionRow key={s.id} session={s} fiat={fiat} />
            ))}
          </ul>
        )}
        {sessions.isFetchNextPageError ? (
          <div className="flex flex-col items-start gap-2">
            <FormError message={describeError(sessions.error)} />
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => sessions.fetchNextPage()}
            >
              Try again
            </Button>
          </div>
        ) : (
          sessions.hasNextPage && (
            <Button
              variant="outline"
              disabled={sessions.isFetchingNextPage || !online}
              onClick={() => sessions.fetchNextPage()}
            >
              Load more
            </Button>
          )
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
