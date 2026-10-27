import {
  useMutationState,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";
import { portfolioKey } from "@/api/queries";

// The confirmations that may send orders, and the read of the balances after
// one. They are held in the mutation cache, not in a screen's state, so the
// user can leave while one runs and find its outcome when they come back. An
// outcome nobody is looking at is dropped after the default gcTime (5
// minutes); History keeps what it did.
export const investKey = ["operation", "invest"] as const;
export const approveKey = ["operation", "approve"] as const;
export const refreshAfterKey = ["operation", "refresh"] as const;

// The request may have reached the platform and placed orders, but no answer
// came back. A 503 is an answer: the platform says nothing was recorded.
export function isLostAnswer(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status === 500 || error.status === 502 || error.status === 504;
}

function forget(client: QueryClient, key: readonly unknown[]): void {
  const cache = client.getMutationCache();
  cache
    .findAll({ mutationKey: key, exact: true })
    .forEach((mutation) => cache.remove(mutation));
}

export function useHeldOperation<T, V = unknown>(
  key: readonly unknown[],
): {
  state: "idle" | "pending" | "success" | "error";
  data: T | undefined;
  error: unknown;
  // What the operation was started with.
  variables: V | undefined;
  release: () => void; // removes the mutation from the cache: the user closed it
} {
  const client = useQueryClient();
  const held = useMutationState({
    filters: { mutationKey: key, exact: true },
    select: (mutation) => ({
      status: mutation.state.status,
      data: mutation.state.data as T | undefined,
      error: mutation.state.error as unknown,
      variables: mutation.state.variables as V | undefined,
    }),
  });
  const latest = held.at(-1);
  return {
    state: latest?.status ?? "idle",
    data: latest?.data,
    error: latest?.error ?? null,
    variables: latest?.variables,
    release: () => forget(client, key),
  };
}

// A confirmation, answered or not, may have written a session: History reads
// it again when it is next shown.
export function historyChanged(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: ["sessions"] });
}

// Started through the client, not a screen's hook, so it runs and lands even
// when the screen that sent the orders is gone.
export function refreshAfter(client: QueryClient): void {
  // Only the latest read's failure is the one an outcome shows.
  forget(client, refreshAfterKey);
  client
    .getMutationCache()
    .build(client, {
      mutationKey: refreshAfterKey,
      mutationFn: () => unwrap(api.POST("/api/portfolio/refresh")),
      onSuccess: (data) => client.setQueryData(portfolioKey, data),
    })
    .execute(undefined)
    // The failure is held in the cache and read from there.
    .catch(() => {});
}
