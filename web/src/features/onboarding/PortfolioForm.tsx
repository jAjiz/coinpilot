import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, describeError, unwrap } from "@/api/client";
import { assetsKey, useAssets } from "@/api/queries";
import type { components } from "@/api/schema";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useOnline } from "@/features/shell/useOnline";
import {
  compare,
  formatMoney,
  formatPercent,
  parseDecimal,
} from "@/lib/decimal";
import { cashTarget, prefillWeights, saveOrder } from "@/lib/portfolio";
import { StepFailed, StepSkeleton } from "./WizardLayout";

const INVALID_TARGET =
  "Enter a percentage from 0 to 100, with up to two decimals.";

type Row = {
  asset: string;
  // "locked" and "unpriced" rows cannot be managed; "tradable" ones can.
  kind: "tradable" | "unpriced" | "locked";
  value: string | null;
  weight: string | null;
  managed: boolean;
  target: string;
  // The stored target of an unpriced row: saving removes it, since Kraken no
  // longer trades the asset against the fiat.
  dropped: string | null;
  error: string | null;
};

function validTarget(text: string): string | null {
  const target = parseDecimal(text, 2);
  return target !== null && compare(target, "100") <= 0 ? target : null;
}

export function PortfolioForm({
  fiat,
  onSaved,
}: {
  fiat: string;
  onSaved: () => Promise<void>;
}) {
  // The refresh is a POST that records the account: it is read once per
  // visit and again only on request.
  const account = useQuery({
    queryKey: ["portfolio", "refresh", fiat],
    queryFn: () => unwrap(api.POST("/api/portfolio/refresh")),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const assets = useAssets();

  // Once the data exists the rows stay, whatever a later refetch does: they
  // hold the user's edits.
  if (account.data === undefined) {
    return account.isError ? (
      <StepFailed
        error={account.error}
        onRetry={() => void account.refetch()}
      />
    ) : (
      <StepSkeleton />
    );
  }
  if (assets.data === undefined) {
    return assets.isError ? (
      <StepFailed error={assets.error} onRetry={() => void assets.refetch()} />
    ) : (
      <StepSkeleton />
    );
  }
  return (
    <Rows
      fiat={fiat}
      account={account.data}
      stored={assets.data.assets}
      onSaved={onSaved}
    />
  );
}

type Account = Pick<components["schemas"]["PortfolioOut"], "cash" | "holdings">;
type StoredAsset = components["schemas"]["AssetOut"];

function initialRows(account: Account, stored: StoredAsset[]): Row[] {
  const weights = prefillWeights(account.cash, account.holdings);
  const storedTarget = new Map(stored.map((s) => [s.asset, s.target_pct]));
  return account.holdings.map((h): Row => {
    const weight = weights.get(h.asset) ?? null;
    const base = {
      asset: h.asset,
      value: h.value,
      weight,
      managed: true,
      dropped: null,
      error: null,
    };
    if (h.locked) {
      return { ...base, kind: "locked", managed: false, target: "" };
    }
    if (h.value === null) {
      return {
        ...base,
        kind: "unpriced",
        managed: false,
        target: "",
        dropped: storedTarget.get(h.asset) ?? null,
      };
    }
    // Decision 4: the stored target for a managed holding, the weight otherwise.
    return {
      ...base,
      kind: "tradable",
      target: storedTarget.get(h.asset) ?? weight ?? "0",
    };
  });
}

function Rows({
  fiat,
  account,
  stored,
  onSaved,
}: {
  fiat: string;
  account: Account;
  stored: StoredAsset[];
  onSaved: () => Promise<void>;
}) {
  const client = useQueryClient();
  const online = useOnline();
  const [rows, setRows] = useState(() => initialRows(account, stored));
  const [newAsset, setNewAsset] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function change(asset: string, patch: Partial<Row>) {
    setRows((current) =>
      current.map((row) => (row.asset === asset ? { ...row, ...patch } : row)),
    );
  }

  function add(event: FormEvent) {
    event.preventDefault();
    const code = newAsset.trim().toUpperCase();
    if (code === "") return;
    if (rows.some((row) => row.asset === code)) {
      setAddError(`${code} is already in the list.`);
      return;
    }
    setAddError(null);
    setNewAsset("");
    setRows([
      ...rows,
      {
        asset: code,
        kind: "tradable",
        value: null,
        weight: null,
        managed: true,
        target: "",
        dropped: null,
        error: null,
      },
    ]);
  }

  const targets = rows.flatMap((row) => {
    const target = row.managed ? validTarget(row.target) : null;
    return target === null ? [] : [target];
  });

  async function save() {
    setFormError(null);
    const checked = rows.map((row) => ({
      ...row,
      error:
        row.kind === "tradable" &&
        row.managed &&
        validTarget(row.target) === null
          ? INVALID_TARGET
          : null,
    }));
    setRows(checked);
    if (checked.some((row) => row.error !== null)) return;

    const wanted = new Map<string, string>();
    for (const row of checked) {
      if (row.kind === "tradable" && row.managed) {
        wanted.set(row.asset, validTarget(row.target)!);
      }
    }
    if (wanted.size === 0) {
      setFormError("Manage at least one asset.");
      return;
    }
    if (compare(cashTarget([...wanted.values()]), "0") < 0) {
      setFormError("The targets add up to more than 100 %.");
      return;
    }

    const order = saveOrder(
      new Map(stored.map((s) => [s.asset, s.target_pct])),
      wanted,
    );
    setSaving(true);
    let failedAt: string | null = null;
    try {
      for (const asset of order.deletes) {
        failedAt = asset;
        await unwrap(
          api.DELETE("/api/assets/{asset}", { params: { path: { asset } } }),
        );
      }
      for (const { asset, target } of order.puts) {
        failedAt = asset;
        await unwrap(
          api.PUT("/api/assets/{asset}", {
            params: { path: { asset } },
            body: { target_pct: target },
          }),
        );
      }
      failedAt = null;
    } catch (error) {
      const message = describeError(error);
      if (rows.some((row) => row.asset === failedAt)) {
        change(failedAt!, { error: message });
      } else {
        setFormError(message);
      }
      // The writes before the failure stand: read them back, so that sending
      // again starts from what is stored.
      await client.invalidateQueries({ queryKey: assetsKey });
    }
    if (failedAt !== null) {
      setSaving(false);
      return;
    }
    // Stays disabled while the step advances: a second tap would send again.
    try {
      await onSaved();
    } catch (error) {
      setFormError(describeError(error));
      setSaving(false);
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Your account</h2>
      <p>
        Targets start at today&apos;s weights, so the first rebalance has
        nothing to do. Change them to where you want the portfolio to be.
      </p>
      {account.holdings.length === 0 && (
        <p>Nothing is held yet; add the assets you want to buy.</p>
      )}
      <ul className="flex flex-col gap-3">
        {rows.map((row) => (
          <li
            key={row.asset}
            aria-label={row.asset}
            className="flex flex-col gap-2 rounded-lg border p-3"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold">{row.asset}</span>
              {row.value !== null && (
                <span>{formatMoney(row.value, fiat)}</span>
              )}
            </div>
            {row.kind === "tradable" && (
              <>
                {row.weight !== null && (
                  <p className="text-sm text-muted-foreground">
                    {formatPercent(row.weight)} of the account
                  </p>
                )}
                <div className="flex items-center gap-3">
                  <Switch
                    aria-label={`Manage ${row.asset}`}
                    checked={row.managed}
                    onCheckedChange={(managed) =>
                      change(row.asset, { managed, error: null })
                    }
                  />
                  <Input
                    aria-label={`Target for ${row.asset}`}
                    inputMode="decimal"
                    value={row.target}
                    disabled={!row.managed}
                    onChange={(event) =>
                      change(row.asset, { target: event.target.value })
                    }
                  />
                  <span aria-hidden>%</span>
                </div>
              </>
            )}
            {row.kind === "unpriced" && (
              <p className="text-sm">
                Kraken has no {row.asset}/{fiat} price, so it cannot be managed.
                {row.dropped !== null &&
                  ` Its ${formatPercent(row.dropped)} target is removed when you save.`}
              </p>
            )}
            {row.kind === "locked" && (
              <p className="text-sm">
                Locked (staked or reserved), so it cannot be managed.
              </p>
            )}
            <FormError message={row.error} />
          </li>
        ))}
      </ul>

      <form onSubmit={add} className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="asset-to-add">Asset to add</Label>
          <Input
            id="asset-to-add"
            placeholder="e.g. SOL"
            autoComplete="off"
            value={newAsset}
            onChange={(event) => setNewAsset(event.target.value)}
          />
        </div>
        <Button type="submit" variant="outline">
          Add
        </Button>
      </form>
      {addError !== null && <p className="text-sm">{addError}</p>}

      <p className="font-semibold">
        Cash ({fiat}) target: {formatPercent(cashTarget(targets))}
      </p>
      <FormError message={formError} />
      <Button onClick={() => void save()} disabled={saving || !online}>
        Save targets
      </Button>
    </section>
  );
}
