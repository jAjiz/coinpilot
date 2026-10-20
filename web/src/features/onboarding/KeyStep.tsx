import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, describeError, unwrap } from "@/api/client";
import { useCredentialStatus } from "@/api/queries";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOnline } from "@/features/shell/useOnline";
import { REQUIRED_PERMISSIONS, refusalMessage } from "@/lib/keys";
import { useAdvance } from "./useAdvance";
import { StepFailed, StepSkeleton, WizardLayout } from "./WizardLayout";

type KeyAccepted = components["schemas"]["KeyAcceptedOut"];

function failureMessage(error: unknown): string {
  const body = error instanceof ApiError ? error.body : undefined;
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  return refusalMessage(detail) ?? describeError(error);
}

export function KeyStep() {
  const status = useCredentialStatus();
  const advance = useAdvance();
  const online = useOnline();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [accepted, setAccepted] = useState<KeyAccepted | null>(null);

  const save = useMutation({
    mutationFn: (body: { api_key: string; api_secret: string }) =>
      unwrap(api.POST("/api/credentials", { body })),
    onSuccess: (reply) => {
      setApiKey("");
      setApiSecret("");
      setAccepted(reply);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setAccepted(null);
    save.mutate({ api_key: apiKey, api_secret: apiSecret });
  }

  const proceed = () => void advance("portfolio");

  if (status.isPending) {
    return (
      <WizardLayout step="key" title="Kraken key">
        <StepSkeleton />
      </WizardLayout>
    );
  }
  if (status.isError) {
    return (
      <WizardLayout step="key" title="Kraken key">
        <StepFailed
          error={status.error}
          onRetry={() => void status.refetch()}
        />
      </WizardLayout>
    );
  }

  const registered = status.data.registered && accepted === null;
  const verifiedOn = status.data.validated_at
    ? new Date(status.data.validated_at).toLocaleDateString(undefined, {
        dateStyle: "long",
      })
    : null;

  return (
    <WizardLayout step="key" title="Kraken key">
      <p>
        CoinPilot trades on your Kraken account through an API key. In Kraken,
        open Settings → API and create a key with exactly these permissions:
      </p>
      <ul className="list-disc pl-5">
        {REQUIRED_PERMISSIONS.map(({ code, label }) => (
          <li key={code}>
            {label} <code className="text-xs">{code}</code>
          </li>
        ))}
      </ul>
      <p className="font-semibold">
        Never enable withdrawal permissions. CoinPilot refuses a key that can
        move funds out.
      </p>

      {registered && (
        <div className="flex flex-col items-start gap-3">
          <p>
            A key is saved{verifiedOn ? `, verified on ${verifiedOn}` : ""}.
          </p>
          <Button onClick={proceed} disabled={!online}>
            Continue
          </Button>
          <h2 className="text-lg font-semibold">Replace the key</h2>
        </div>
      )}

      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="api-key">API key</Label>
          <Input
            id="api-key"
            type="password"
            autoComplete="off"
            required
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="api-secret">Private key</Label>
          <Input
            id="api-secret"
            type="password"
            autoComplete="off"
            required
            value={apiSecret}
            onChange={(event) => setApiSecret(event.target.value)}
          />
        </div>
        <FormError message={save.isError ? failureMessage(save.error) : null} />
        <Button type="submit" disabled={save.isPending || !online}>
          {save.isPending ? "Verifying with Kraken…" : "Verify & save"}
        </Button>
      </form>

      {accepted && (
        <div className="flex flex-col items-start gap-3">
          <p role="status">Key saved.</p>
          {accepted.unnecessary.length > 0 && (
            <p>
              This key also has permissions CoinPilot does not need:{" "}
              {accepted.unnecessary.join(", ")}. Turn them off in Kraken.
            </p>
          )}
          {accepted.ip_allowlist.length === 0 && (
            <p>
              Restrict the key to your server&apos;s IP address in Kraken, so
              that it is useless anywhere else.
            </p>
          )}
          <Button onClick={proceed} disabled={!online}>
            Continue
          </Button>
        </div>
      )}
    </WizardLayout>
  );
}
