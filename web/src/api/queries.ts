import {
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
