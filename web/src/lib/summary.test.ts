import { expect, test } from "vitest";
import {
  formatRun,
  ordinal,
  startsLater,
  summarize,
  type SummaryInput,
} from "./summary";

const base: SummaryInput = {
  fiat: "EUR",
  invest: { kind: "choice", choice: "weekly", date: "2026-10-19" },
  rebalance: { kind: "choice", choice: "quarterly", date: "2026-10-01" },
  invest_cash_enabled: true,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  min_drift_pct: "1.0",
  min_order_fiat: "0",
};

test("the spec's example, word for word", () => {
  expect(summarize(base)).toEqual([
    "Every Monday at 12:00, free EUR is invested toward your targets.",
    "On the 1st of every quarter, if any asset has drifted more than 1 %, a rebalance is proposed for you to approve.",
  ]);
});

test("invest disabled says so", () => {
  expect(summarize({ ...base, invest_cash_enabled: false })[0]).toBe(
    "Free EUR is not invested automatically; you can invest it from Home.",
  );
});

test("as soon as possible, daily, monthly on the 31st", () => {
  const first = (invest: SummaryInput["invest"]) =>
    summarize({ ...base, invest })[0];
  expect(first({ kind: "choice", choice: "asap", date: "2026-10-19" })).toBe(
    "Every 15 minutes, free EUR is invested toward your targets.",
  );
  expect(first({ kind: "choice", choice: "daily", date: "2026-10-19" })).toBe(
    "Every day at 12:00, free EUR is invested toward your targets.",
  );
  expect(first({ kind: "choice", choice: "monthly", date: "2026-10-31" })).toBe(
    "On the 31st of every month at 12:00 (or the last day of a shorter month), free EUR is invested toward your targets.",
  );
});

test("buying the most underweight first", () => {
  expect(summarize({ ...base, cash_rebalance_enabled: true })[0]).toBe(
    "Every Monday at 12:00, free EUR is invested in the most underweight assets first.",
  );
});

test("yearly, half-yearly, automatic, no drift threshold", () => {
  const second = (
    choice: "monthly" | "half-yearly" | "yearly",
    date: string,
    extra: Partial<SummaryInput> = {},
  ) =>
    summarize({
      ...base,
      rebalance: { kind: "choice", choice, date },
      ...extra,
    })[1];
  expect(
    second("yearly", "2027-01-15", {
      min_drift_pct: "0",
      auto_rebalance_enabled: true,
    }),
  ).toBe(
    "Every year on 15 January, if any asset is off its target, the portfolio is rebalanced without asking.",
  );
  expect(second("half-yearly", "2026-10-02")).toBe(
    "On the 2nd every six months, if any asset has drifted more than 1 %, a rebalance is proposed for you to approve.",
  );
  expect(second("monthly", "2026-10-30")).toBe(
    "On the 30th of every month (or the last day of a shorter month), if any asset has drifted more than 1 %, a rebalance is proposed for you to approve.",
  );
});

test("a minimum order adds a sentence", () => {
  const out = summarize({ ...base, min_order_fiat: "10" });
  expect(out).toHaveLength(3);
  expect(out[2]).toBe("Orders smaller than €10.00 are skipped.");
});

test("custom cadences", () => {
  const out = summarize({
    ...base,
    invest: { kind: "custom" },
    rebalance: { kind: "custom" },
  });
  expect(out[0]).toBe(
    "On a custom schedule, free EUR is invested toward your targets.",
  );
  expect(out[1]).toBe(
    "On a custom schedule, if any asset has drifted more than 1 %, a rebalance is proposed for you to approve.",
  );
});

test("ordinals", () => {
  expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31].map(ordinal)).toEqual([
    "1st",
    "2nd",
    "3rd",
    "4th",
    "11th",
    "12th",
    "13th",
    "21st",
    "22nd",
    "23rd",
    "31st",
  ]);
});

test("a run is told in local time", () => {
  expect(formatRun("2026-10-26T11:37:00Z")).toBe("Monday 26 October at 12:37");
});

test("a start date that has passed begins later", () => {
  const weekly = base.invest;
  expect(startsLater(weekly, "2026-10-26T10:20:00Z")).toBe(true);
  expect(startsLater(weekly, "2026-10-19T10:20:00Z")).toBe(false);
  expect(
    startsLater(
      { kind: "choice", choice: "asap", date: "2026-10-12" },
      "2026-10-26T10:20:00Z",
    ),
  ).toBe(false);
  expect(startsLater({ kind: "custom" }, "2026-10-26T10:20:00Z")).toBe(false);
  expect(startsLater(weekly, null)).toBe(false);
});
