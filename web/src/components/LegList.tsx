import type { components } from "@/api/schema";
import { legLine, legStatus } from "@/lib/operations";

type Leg = components["schemas"]["LegOut"];

export function LegList({ legs, fiat }: { legs: Leg[]; fiat: string }) {
  return (
    <ul className="flex flex-col gap-1">
      {legs.map((leg) => (
        <li key={`${leg.side}-${leg.asset}`}>
          <span>{legLine(leg, fiat)}</span>
          <span className="block text-sm text-muted-foreground">
            {legStatus(leg)}
          </span>
        </li>
      ))}
    </ul>
  );
}
