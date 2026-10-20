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
// was saved by the wizard: every value is the wizard's own default. Once it is
// INTERVAL, every value is the saved one.
export function wizardValues(config: Config, today: string): AutomationValues {
  if (config.rebalance_cadence_mode === "MIN") {
    return {
      invest: { kind: "choice", choice: "monthly", date: today },
      rebalance: { kind: "choice", choice: "quarterly", date: today },
      invest_cash_enabled: false,
      cash_rebalance_enabled: false,
      auto_rebalance_enabled: false,
      min_drift_pct: "1",
      min_order_fiat: "0",
    };
  }
  return {
    invest: readInvest(cadenceOf(config, "invest"), today),
    rebalance: readRebalance(cadenceOf(config, "rebalance"), today),
    invest_cash_enabled: config.invest_cash_enabled,
    cash_rebalance_enabled: config.cash_rebalance_enabled,
    auto_rebalance_enabled: config.auto_rebalance_enabled,
    min_drift_pct: config.min_drift_pct,
    min_order_fiat: config.min_order_fiat,
  };
}
