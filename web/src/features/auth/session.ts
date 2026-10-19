import { useQuery } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { onboardingStep, type OnboardingStep } from "@/lib/onboarding";

export const meKey = ["me"] as const;
export const onboardingKey = ["onboarding"] as const;

export type Me = components["schemas"]["MeOut"];
export type Onboarding =
  { onboarded: true } | { onboarded: false; step: OnboardingStep };

export async function fetchMe(): Promise<Me | null> {
  try {
    return await unwrap(api.GET("/api/auth/me"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function fetchOnboarding(): Promise<Onboarding> {
  let fiat: string | null = null;
  try {
    const config = await unwrap(api.GET("/api/config"));
    if (config.onboarded_at) return { onboarded: true };
    fiat = config.fiat;
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error;
  }
  const [status, assets] = await Promise.all([
    unwrap(api.GET("/api/credentials/status")),
    unwrap(api.GET("/api/assets")),
  ]);
  return {
    onboarded: false,
    step: onboardingStep({
      keyRegistered: status.registered,
      fiat,
      assetCount: assets.assets.length,
    }),
  };
}

export function useMe() {
  return useQuery({ queryKey: meKey, queryFn: fetchMe });
}

export function useOnboarding() {
  const me = useMe();
  return useQuery({
    queryKey: onboardingKey,
    queryFn: fetchOnboarding,
    enabled: Boolean(me.data),
  });
}
