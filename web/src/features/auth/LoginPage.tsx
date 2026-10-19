import { Navigate, useSearchParams } from "react-router";
import { FullPageSkeleton } from "@/components/FullPageSkeleton";
import { buttonVariants } from "@/components/ui/button";
import { useMe } from "./session";

export function LoginPage() {
  const me = useMe();
  const [params] = useSearchParams();
  const error = params.get("error");
  if (me.isPending) return <FullPageSkeleton />;
  if (me.data) return <Navigate to="/" replace />;
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-start justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">CoinPilot</h1>
      <p>Keeps your Kraken portfolio on its targets.</p>
      {error && <p role="alert">{error}</p>}
      <a
        href="/api/auth/login/google"
        className={buttonVariants({ size: "lg" })}
      >
        Sign in with Google
      </a>
    </main>
  );
}
