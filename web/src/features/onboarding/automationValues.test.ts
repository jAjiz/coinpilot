import { expect, test } from "vitest";
import type { Config } from "@/api/queries";
import { settingsValues } from "./automationValues";

const CONFIG: Config = {
  fiat: "EUR",
  invest_cash_enabled: false,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "0",
  min_order_fiat: "0",
  invest_cadence_mode: "MIN",
  invest_interval_days: null,
  invest_interval_months: null,
  invest_cadence_anchor: null,
  rebalance_cadence_mode: "MIN",
  rebalance_interval_days: null,
  rebalance_interval_months: null,
  rebalance_cadence_anchor: null,
  next_invest_at: null,
  next_rebalance_at: null,
  onboarded_at: "2026-10-01T00:00:00Z",
};

test("settings values keep a stored MIN rebalance as custom", () => {
  const values = settingsValues(CONFIG, "2026-10-27");
  expect(values.rebalance).toEqual({ kind: "custom" });
  expect(values.invest).toEqual({
    kind: "choice",
    choice: "asap",
    date: "2026-10-27",
  });
});

test("settings values keep switches and thresholds as stored", () => {
  // Entirely at the platform's defaults, the wizard would start from its own.
  const values = settingsValues(CONFIG, "2026-10-27");
  expect(values.invest_cash_enabled).toBe(false);
  expect(values.min_drift_pct).toBe("0");
  expect(values.min_order_fiat).toBe("0");
  const stored = settingsValues(
    {
      ...CONFIG,
      invest_cash_enabled: true,
      auto_rebalance_enabled: true,
      min_drift_pct: "2.5",
      min_order_fiat: "10",
    },
    "2026-10-27",
  );
  expect(stored).toMatchObject({
    invest_cash_enabled: true,
    cash_rebalance_enabled: false,
    auto_rebalance_enabled: true,
    min_drift_pct: "2.5",
    min_order_fiat: "10",
  });
});
