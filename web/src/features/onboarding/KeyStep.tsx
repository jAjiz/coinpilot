import { useState, type FormEvent, type ReactNode } from "react";
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

// Shown in clear so a paste can be checked on a phone. The keyboard must not touch it:
// a capitalised or "corrected" character makes Kraken refuse the key.
function KeyField(props: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={props.id}>{props.label}</Label>
      <Input
        id={props.id}
        type="text"
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        required
        aria-describedby={`${props.id}-hint`}
        className="font-mono"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      />
      <p id={`${props.id}-hint`} className="text-sm text-muted-foreground">
        {props.hint}
      </p>
    </div>
  );
}

export function KeyStep() {
  const status = useCredentialStatus();
  const advance = useAdvance();
  const online = useOnline();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [accepted, setAccepted] = useState<KeyAccepted | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [advancing, setAdvancing] = useState(false);

  // Not a useMutation: its cache would keep the key and secret as `variables`.
  async function submit(event: FormEvent) {
    event.preventDefault();
    setAccepted(null);
    setFailure(null);
    setSending(true);
    try {
      const reply = await unwrap(
        api.POST("/api/credentials", {
          body: { api_key: apiKey, api_secret: apiSecret },
        }),
      );
      setApiKey("");
      setApiSecret("");
      setAccepted(reply);
    } catch (error) {
      setFailure(failureMessage(error));
    } finally {
      setSending(false);
    }
  }

  async function proceed() {
    setAdvancing(true);
    try {
      await advance("portfolio");
    } finally {
      setAdvancing(false);
    }
  }

  const layout = (children: ReactNode) => (
    <WizardLayout step="key" title="Kraken key">
      {children}
    </WizardLayout>
  );

  if (status.isPending) return layout(<StepSkeleton />);
  if (status.isError) {
    return layout(
      <StepFailed error={status.error} onRetry={() => void status.refetch()} />,
    );
  }

  const registered = status.data.registered && accepted === null;
  const verifiedOn = status.data.validated_at
    ? new Date(status.data.validated_at).toLocaleDateString("en-GB", {
        dateStyle: "long",
      })
    : null;

  return layout(
    <>
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
          <Button
            onClick={() => void proceed()}
            disabled={!online || advancing}
          >
            Continue
          </Button>
          <h2 className="text-lg font-semibold">Replace the key</h2>
        </div>
      )}

      <form
        onSubmit={(event) => void submit(event)}
        className="flex flex-col gap-4"
      >
        <KeyField
          id="api-key"
          label="API key"
          hint="Kraken's “API Key”: the shorter value."
          value={apiKey}
          onChange={setApiKey}
        />
        <KeyField
          id="api-secret"
          label="Private key"
          hint="Kraken's “Private Key”: the longer value."
          value={apiSecret}
          onChange={setApiSecret}
        />
        <FormError message={failure} />
        <Button type="submit" disabled={sending || !online}>
          {sending ? "Verifying with Kraken…" : "Verify & save"}
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
          <Button
            onClick={() => void proceed()}
            disabled={!online || advancing}
          >
            Continue
          </Button>
        </div>
      )}
    </>,
  );
}
