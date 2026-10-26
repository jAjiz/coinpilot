import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api, operationError, unwrap } from "@/api/client";
import { proposalKey } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { useOnline } from "@/features/shell/useOnline";

export function RebalanceNow() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const online = useOnline();
  const [messages, setMessages] = useState<string[] | null>(null);
  // Set synchronously, so a second tap in the same tick cannot send again.
  const sending = useRef(false);

  const rebalance = useMutation({
    mutationFn: () => unwrap(api.POST("/api/rebalance")),
    onSuccess: async (result) => {
      if (result.status === "PROPOSED" && result.proposal) {
        client.setQueryData(proposalKey, result.proposal);
        void navigate("/proposal");
        return;
      }
      setMessages(result.messages);
      // An evaluation that finds nothing may have withdrawn a proposal.
      await client.invalidateQueries({ queryKey: proposalKey });
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  function start() {
    if (sending.current) return;
    sending.current = true;
    setMessages(null);
    rebalance.mutate();
  }

  return (
    <section className="flex flex-col items-start gap-3">
      <h2 className="text-lg font-semibold">Rebalance now</h2>
      <p>
        Compare the account with your targets. A rebalance is proposed for you
        to review; nothing is sent until you approve it.
      </p>
      <Button onClick={start} disabled={rebalance.isPending || !online}>
        {rebalance.isPending ? "Checking…" : "Rebalance now"}
      </Button>
      {messages !== null && (
        <>
          <p>Nothing to rebalance.</p>
          {messages.map((m) => (
            <p key={m}>{m}</p>
          ))}
        </>
      )}
      <FormError
        message={rebalance.isError ? operationError(rebalance.error) : null}
      />
    </section>
  );
}
