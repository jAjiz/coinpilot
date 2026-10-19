import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { onSessionEnded } from "@/api/client";
import { meKey } from "@/features/auth/session";

// oxlint-disable-next-line react/only-export-components -- the plan keeps both here
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
}

export function Providers({
  client,
  children,
}: {
  client: QueryClient;
  children: ReactNode;
}) {
  useEffect(
    () =>
      onSessionEnded(() => {
        // The "me" query stays: a mounted guard observes it, and removing it
        // would leave that guard waiting for a query nobody fills.
        client.removeQueries({
          predicate: (query) => query.queryKey[0] !== meKey[0],
        });
        client.setQueryData(meKey, null);
      }),
    [client],
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
