import { Link } from "react-router";
import { useConfig } from "@/api/queries";
import { AccountValue } from "./AccountValue";
import { Allocation } from "./Allocation";
import { InvestNow } from "./InvestNow";
import { ProposalCard } from "./ProposalCard";
import { RebalanceNow } from "./RebalanceNow";

export function DashboardPage() {
  const config = useConfig();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Home</h1>
      {config.data?.paused && (
        <p>
          Automation is paused.{" "}
          <Link to="/settings" className="underline">
            Resume in Settings
          </Link>
        </p>
      )}
      <ProposalCard />
      <AccountValue />
      <Allocation />
      <InvestNow />
      <RebalanceNow />
    </div>
  );
}
