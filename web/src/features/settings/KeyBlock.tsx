import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, describeError, unwrap } from "@/api/client";
import { credentialStatusKey, useCredentialStatus } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  KeyAcceptedNotes,
  KeyForm,
  type KeyAccepted,
} from "@/features/onboarding/KeyForm";
import { useOnline } from "@/features/shell/useOnline";
import { verifiedOn } from "@/lib/keys";

export function KeyBlock() {
  const client = useQueryClient();
  const status = useCredentialStatus();
  const online = useOnline();
  const [replacing, setReplacing] = useState(false);
  const [accepted, setAccepted] = useState<KeyAccepted | null>(null);
  const [confirming, setConfirming] = useState(false);

  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/credentials")),
    // A 404 says there was no key: the status read below shows that too.
    // Whatever the answer, the confirmation is spent: the next delete, of a
    // key saved later, takes its own second tap.
    onSettled: () => {
      setConfirming(false);
      return client.invalidateQueries({ queryKey: credentialStatusKey });
    },
    onSuccess: () => {
      setReplacing(false);
      setAccepted(null);
    },
  });

  let body;
  if (status.isPending) {
    body = <Skeleton className="h-16 w-full" />;
  } else if (status.isError) {
    body = (
      <>
        <FormError message={describeError(status.error)} />
        <Button onClick={() => void status.refetch()}>Try again</Button>
      </>
    );
  } else if (!status.data.registered) {
    body = (
      <>
        <p>No key is saved. CoinPilot cannot trade until you save one.</p>
        <KeyForm
          onAccepted={(reply) => {
            setAccepted(reply);
            void client.invalidateQueries({ queryKey: credentialStatusKey });
          }}
        />
        {accepted && <KeyAcceptedNotes accepted={accepted} />}
      </>
    );
  } else {
    const verified = verifiedOn(status.data.validated_at);
    body = (
      <>
        <p>A key is saved{verified ? `, verified on ${verified}` : ""}.</p>
        {accepted && <KeyAcceptedNotes accepted={accepted} />}
        {replacing ? (
          <KeyForm
            onStart={() => setAccepted(null)}
            onAccepted={(reply) => {
              setAccepted(reply);
              setReplacing(false);
              void client.invalidateQueries({ queryKey: credentialStatusKey });
            }}
          />
        ) : (
          <Button
            variant="outline"
            onClick={() => {
              setAccepted(null);
              setReplacing(true);
            }}
          >
            Replace key
          </Button>
        )}
        {confirming ? (
          <>
            <p>
              Without a key, CoinPilot stops investing and rebalancing until you
              save a new one.
            </p>
            <Button
              variant="destructive"
              onClick={() => remove.mutate()}
              disabled={!online || remove.isPending}
            >
              Confirm: delete key
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            onClick={() => {
              remove.reset();
              setConfirming(true);
            }}
            disabled={!online || remove.isPending}
          >
            Delete key
          </Button>
        )}
        {remove.isError && <FormError message={describeError(remove.error)} />}
      </>
    );
  }

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Kraken key</h2>
      {body}
    </section>
  );
}
