import { AccountValue } from "./AccountValue";
import { Allocation } from "./Allocation";

export function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Home</h1>
      <AccountValue />
      <Allocation />
    </div>
  );
}
