import { useQuery, type QueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { onboardingKey } from "@/features/auth/session";

export const configKey = ["config"] as const;
export const assetsKey = ["assets"] as const;
export const credentialStatusKey = ["credentials", "status"] as const;

export type Config = components["schemas"]["ConfigOut"];

async function fetchConfig(): Promise<Config | null> {
  try {
    return await unwrap(api.GET("/api/config"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function useConfig() {
  return useQuery({ queryKey: configKey, queryFn: fetchConfig });
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
