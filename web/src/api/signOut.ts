import type { QueryClient } from "@tanstack/react-query";

// A sign-out ends one user's time on a client. A request that was sent before
// it may still answer after it; that answer is the previous user's, and must
// not touch the cache or move the page. A callback takes a guard when its
// request starts and asks it before every write to the cache and every
// navigation that follows the await.
const epochs = new WeakMap<QueryClient, number>();

export function endSession(client: QueryClient): void {
  epochs.set(client, (epochs.get(client) ?? 0) + 1);
}

export function sessionGuard(client: QueryClient): () => boolean {
  const started = epochs.get(client) ?? 0;
  return () => (epochs.get(client) ?? 0) === started;
}
