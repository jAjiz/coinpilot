import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, describeError, unwrap } from "@/api/client";
import { configKey, useConfig } from "@/api/queries";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useOnline } from "@/features/shell/useOnline";
import { FIATS } from "@/lib/fiats";
import { PortfolioForm } from "./PortfolioForm";
import { useAdvance } from "./useAdvance";
import { StepFailed, StepSkeleton, WizardLayout } from "./WizardLayout";

function CurrencyForm() {
  const client = useQueryClient();
  const online = useOnline();
  const [fiat, setFiat] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailure(null);
    setSending(true);
    try {
      await unwrap(api.PATCH("/api/config", { body: { fiat } }));
      await client.invalidateQueries({ queryKey: configKey });
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setSending(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-4"
    >
      <h2 className="text-lg font-semibold">Currency</h2>
      <p>
        The currency your portfolio is valued and traded in. It cannot be
        changed later.
      </p>
      <Label htmlFor="fiat" className="sr-only">
        Currency
      </Label>
      <select
        id="fiat"
        value={fiat}
        onChange={(event) => setFiat(event.target.value)}
        className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-base md:text-sm"
      >
        <option value="" disabled>
          Choose a currency
        </option>
        {FIATS.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </select>
      <FormError message={failure} />
      <Button type="submit" disabled={fiat === "" || sending || !online}>
        Save currency
      </Button>
    </form>
  );
}

export function PortfolioStep() {
  const config = useConfig();
  const advance = useAdvance();

  return (
    <WizardLayout step="portfolio" title="Portfolio">
      {config.isPending ? (
        <StepSkeleton />
      ) : config.isError ? (
        <StepFailed
          error={config.error}
          onRetry={() => void config.refetch()}
        />
      ) : config.data === null ? (
        <CurrencyForm />
      ) : (
        <>
          <p>Currency: {config.data.fiat}</p>
          <PortfolioForm
            fiat={config.data.fiat}
            onSaved={() => advance("automation")}
          />
        </>
      )}
    </WizardLayout>
  );
}
