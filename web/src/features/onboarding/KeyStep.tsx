import { useState, type ReactNode } from "react";
import { useCredentialStatus } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { useOnline } from "@/features/shell/useOnline";
import { REQUIRED_PERMISSIONS, verifiedOn } from "@/lib/keys";
import { KeyAcceptedNotes, KeyForm, type KeyAccepted } from "./KeyForm";
import { useAdvance } from "./useAdvance";
import { StepFailed, StepSkeleton, WizardLayout } from "./WizardLayout";

export function KeyStep() {
  const status = useCredentialStatus();
  const advance = useAdvance();
  const online = useOnline();
  const [accepted, setAccepted] = useState<KeyAccepted | null>(null);
  const [advancing, setAdvancing] = useState(false);

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
  const verified = verifiedOn(status.data.validated_at);

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
          <p>A key is saved{verified ? `, verified on ${verified}` : ""}.</p>
          <Button
            onClick={() => void proceed()}
            disabled={!online || advancing}
          >
            Continue
          </Button>
          <h2 className="text-lg font-semibold">Replace the key</h2>
        </div>
      )}

      <KeyForm onAccepted={setAccepted} onStart={() => setAccepted(null)} />

      {accepted && (
        <div className="flex flex-col items-start gap-3">
          <KeyAcceptedNotes accepted={accepted} />
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
