import { useState } from "react";
import { useNavigate } from "react-router";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { onboardingKey } from "@/features/auth/session";

export const configKey = ["config"] as const;
export const assetsKey = ["assets"] as const;
export const credentialStatusKey = ["credentials", "status"] as const;

export const portfolioKey = ["portfolio"] as const;
export const proposalKey = ["proposal"] as const;

export type Config = components["schemas"]["ConfigOut"];
export type Portfolio = components["schemas"]["PortfolioOut"];
export type Proposal = components["schemas"]["ProposalOut"];

// A 404 means "nothing there yet", which is an answer, not a failure.
async function orNull<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T | null> {
  try {
    return await unwrap(call);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function useConfig() {
  return useQuery({
    queryKey: configKey,
    queryFn: () => orNull(api.GET("/api/config")),
  });
}

export function usePortfolio() {
  return useQuery({
    queryKey: portfolioKey,
    queryFn: () => orNull(api.GET("/api/portfolio")),
  });
}

export function useProposal() {
  return useQuery({
    queryKey: proposalKey,
    queryFn: () => orNull(api.GET("/api/proposal")),
  });
}

export const SESSIONS_PAGE = 20;

// Newest first; each page continues strictly after the last id of the one before.
export function useSessions() {
  return useInfiniteQuery({
    queryKey: ["sessions"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/sessions", {
          params: {
            query: {
              limit: SESSIONS_PAGE,
              ...(pageParam === null ? {} : { before: pageParam }),
            },
          },
        }),
      ),
    getNextPageParam: (last) =>
      last.length < SESSIONS_PAGE ? undefined : last[last.length - 1].id,
  });
}

export function useSessionOrders(sessionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["orders", sessionId],
    queryFn: () =>
      unwrap(
        api.GET("/api/orders", { params: { query: { session: sessionId } } }),
      ),
    enabled,
  });
}

export function useRefreshPortfolio() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/portfolio/refresh")),
    onSuccess: (data) => client.setQueryData(portfolioKey, data),
  });
}

export function useAssets() {
  return useQuery({
    queryKey: assetsKey,
    queryFn: () => unwrap(api.GET("/api/assets")),
  });
}

export function useCredentialStatus() {
  return useQuery({
    queryKey: credentialStatusKey,
    queryFn: () => unwrap(api.GET("/api/credentials/status")),
  });
}

export async function invalidateAccount(client: QueryClient): Promise<void> {
  await Promise.all(
    [configKey, assetsKey, credentialStatusKey, onboardingKey].map((queryKey) =>
      client.invalidateQueries({ queryKey }),
    ),
  );
}

// Nothing of this user may outlive the sign-out: the queries and the mutations
// the cache holds (an invest outcome, a read of the balances) go before /login
// opens. A failed request leaves everything as it was: the cookies still stand.
export function useSignOut(): {
  signOut: () => Promise<void>;
  pending: boolean;
  error: unknown;
} {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function signOut() {
    setPending(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/logout"));
    } catch (failure) {
      setError(failure);
      setPending(false);
      return;
    }
    await client.cancelQueries();
    client.clear();
    await navigate("/login", { replace: true });
  }

  return { signOut, pending, error };
}
