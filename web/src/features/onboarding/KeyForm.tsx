import { useState, type FormEvent } from "react";
import { ApiError, api, describeError, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOnline } from "@/features/shell/useOnline";
import { refusalMessage } from "@/lib/keys";

export type KeyAccepted = components["schemas"]["KeyAcceptedOut"];

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

// What an accepted key leaves to say; the caller adds what comes next.
export function KeyAcceptedNotes({ accepted }: { accepted: KeyAccepted }) {
  return (
    <>
      <p role="status">Key saved.</p>
      {accepted.unnecessary.length > 0 && (
        <p>
          This key also has permissions CoinPilot does not need:{" "}
          {accepted.unnecessary.join(", ")}. Turn them off in Kraken.
        </p>
      )}
      {accepted.ip_allowlist.length === 0 && (
        <p>
          Restrict the key to your server&apos;s IP address in Kraken, so that
          it is useless anywhere else.
        </p>
      )}
    </>
  );
}

export function KeyForm({
  onAccepted,
  onStart,
}: {
  onAccepted: (reply: KeyAccepted) => void;
  onStart?: () => void;
}) {
  const online = useOnline();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Not a useMutation: its cache would keep the key and secret as `variables`.
  async function submit(event: FormEvent) {
    event.preventDefault();
    onStart?.();
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
      onAccepted(reply);
    } catch (error) {
      setFailure(failureMessage(error));
    } finally {
      setSending(false);
    }
  }

  return (
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
  );
}
