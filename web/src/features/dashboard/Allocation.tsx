import { useConfig, usePortfolio } from "@/api/queries";
import { allocationRows, formatDrift, type AllocationRow } from "@/lib/account";
import {
  compare,
  formatAmount,
  formatMoney,
  formatPercent,
} from "@/lib/decimal";
import { cn } from "cn";

// A weight outside 0-100 would draw outside the track.
function clamp(weight: string): string {
  if (compare(weight, "0") < 0) return "0";
  if (compare(weight, "100") > 0) return "100";
  return weight;
}

function Bar({ weight, target }: { weight: string; target: string | null }) {
  return (
    <div
      aria-hidden
      className="relative h-2 overflow-hidden rounded-full bg-muted"
    >
      <div
        data-slot="fill"
        className="h-full rounded-full bg-primary"
        style={{ width: `${clamp(weight)}%` }}
      />
      {target !== null && (
        <div
          data-slot="mark"
          className="absolute top-0 h-full w-0.5 bg-foreground"
          style={{ left: `${clamp(target)}%` }}
        />
      )}
    </div>
  );
}

// "0.0123 BTC · €325.00"; cash is its value alone, and a missing part is left out.
function holding(row: AllocationRow, fiat: string): string | null {
  const parts = [
    ...(row.amount === null
      ? []
      : [`${formatAmount(row.amount)} ${row.asset}`]),
    ...(row.value === null ? [] : [formatMoney(row.value, fiat)]),
  ];
  return parts.length === 0 ? null : parts.join(" · ");
}

function Row({ row, fiat }: { row: AllocationRow; fiat: string }) {
  const held = holding(row, fiat);
  return (
    <li
      aria-label={row.asset}
      data-drifted={row.drifted ? "true" : undefined}
      className="flex flex-col gap-2 rounded-lg border p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold">{row.asset}</span>
        {row.drift !== null && (
          <span
            className={cn(
              "text-sm",
              row.drifted && "font-semibold text-amber-600 dark:text-amber-400",
            )}
          >
            {formatDrift(row.drift)}
          </span>
        )}
      </div>
      {held !== null && <p data-slot="holding">{held}</p>}
      {row.weight === null ? (
        <p className="text-sm text-muted-foreground">
          {row.kind === "cash"
            ? "Not recorded in this reading"
            : `No price in ${fiat}`}
        </p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {formatPercent(row.weight)}
            {row.target !== null && ` · target ${formatPercent(row.target)}`}
          </p>
          <Bar weight={row.weight} target={row.target} />
        </>
      )}
    </li>
  );
}

export function Allocation() {
  const portfolio = usePortfolio();
  const config = useConfig();
  // AccountValue carries the loading, empty and failed states.
  const snapshot = portfolio.data;
  if (!snapshot || !config.data) return null;
  const rows = allocationRows(snapshot, config.data.min_drift_pct);
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Allocation</h2>
      <ul className="flex flex-col gap-3">
        {rows.map((row) => (
          <Row key={row.asset} row={row} fiat={snapshot.fiat} />
        ))}
      </ul>
    </section>
  );
}
