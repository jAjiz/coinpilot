import { Link } from "react-router";
import { useProposal } from "@/api/queries";
import { proposalTotals } from "@/lib/account";
import { formatMoney } from "@/lib/decimal";
import { countOrders } from "@/lib/operations";
import { formatRun } from "@/lib/summary";

// Nothing while loading, empty or failed: Home stays usable without it.
export function ProposalCard() {
  const proposal = useProposal();
  const data = proposal.data;
  if (data === undefined || data === null) return null;

  const totals = proposalTotals(data.legs);
  return (
    <section
      aria-labelledby="proposal-card"
      className="flex flex-col gap-2 rounded-lg border p-4"
    >
      <h2 id="proposal-card" className="font-semibold">
        Rebalance proposal
      </h2>
      <p>
        {countOrders(totals.orders)} for {formatMoney(totals.total, data.fiat)}
      </p>
      <p className="text-sm text-muted-foreground">
        Proposed {formatRun(data.updated_at)}
      </p>
      <Link to="/proposal" className="font-medium underline">
        Review
      </Link>
    </section>
  );
}
