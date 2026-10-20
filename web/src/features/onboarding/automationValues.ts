import type { Config } from "@/api/queries";
import {
  cadenceOf,
  readInvest,
  readRebalance,
  type CadenceForm,
  type InvestChoice,
  type RebalanceChoice,
} from "@/lib/cadence";

export type AutomationValues = {
  invest: CadenceForm<InvestChoice>;
  rebalance: CadenceForm<RebalanceChoice>;
  invest_cash_enabled: boolean;
  cash_rebalance_enabled: boolean;
  auto_rebalance_enabled: boolean;
  min_drift_pct: string;
  min_order_fiat: string;
};

// While the rebalance cadence is still the platform's default (MIN), nothing
// was saved by the wizard: it starts from its own defaults, not from the
// configuration.
export function wizardValues(config: Config, today: string): AutomationValues {
  const common = {
    invest_cash_enabled: config.invest_cash_enabled,
    cash_rebalance_enabled: config.cash_rebalance_enabled,
    auto_rebalance_enabled: config.auto_rebalance_enabled,
    min_order_fiat: config.min_order_fiat,
  };
  if (config.rebalance_cadence_mode === "MIN") {
    return {
      ...common,
      invest: { kind: "choice", choice: "monthly", date: today },
      rebalance: { kind: "choice", choice: "quarterly", date: today },
      min_drift_pct: "1",
    };
  }
  return {
    ...common,
    invest: readInvest(cadenceOf(config, "invest"), today),
    rebalance: readRebalance(cadenceOf(config, "rebalance"), today),
    min_drift_pct: config.min_drift_pct,
  };
}
