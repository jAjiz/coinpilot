import type { Config } from "@/api/queries";
import {
  cadenceOf,
  readInvest,
  readRebalance,
  type CadenceForm,
  type InvestChoice,
  type RebalanceChoice,
} from "@/lib/cadence";
import { compare } from "@/lib/decimal";

export type AutomationValues = {
  invest: CadenceForm<InvestChoice>;
  rebalance: CadenceForm<RebalanceChoice>;
  invest_cash_enabled: boolean;
  cash_rebalance_enabled: boolean;
  auto_rebalance_enabled: boolean;
  min_drift_pct: string;
  min_order_fiat: string;
};

// A configuration still entirely at the platform's defaults was never saved:
// it starts from the wizard's own defaults. Otherwise every saved value is
// shown, and only a rebalance cadence still at MIN (the wizard always saves an
// interval) takes the wizard's default.
function untouched(config: Config): boolean {
  return (
    config.invest_cadence_mode === "MIN" &&
    config.rebalance_cadence_mode === "MIN" &&
    !config.invest_cash_enabled &&
    !config.cash_rebalance_enabled &&
    !config.auto_rebalance_enabled &&
    compare(config.min_drift_pct, "0") === 0 &&
    compare(config.min_order_fiat, "0") === 0
  );
}

export function wizardValues(config: Config, today: string): AutomationValues {
  if (untouched(config)) {
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
    rebalance:
      config.rebalance_cadence_mode === "MIN"
        ? { kind: "choice", choice: "quarterly", date: today }
        : readRebalance(cadenceOf(config, "rebalance")),
    invest_cash_enabled: config.invest_cash_enabled,
    cash_rebalance_enabled: config.cash_rebalance_enabled,
    auto_rebalance_enabled: config.auto_rebalance_enabled,
    min_drift_pct: config.min_drift_pct,
    min_order_fiat: config.min_order_fiat,
  };
}
