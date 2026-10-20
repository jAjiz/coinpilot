import {
  localDate,
  type CadenceForm,
  type InvestChoice,
  type RebalanceChoice,
} from "./cadence";
import { compare, formatMoney, formatPercent } from "./decimal";

// Tells a configuration in English sentences, for the wizard's last step.

export type SummaryInput = {
  fiat: string;
  invest: CadenceForm<InvestChoice>;
  rebalance: CadenceForm<RebalanceChoice>;
  invest_cash_enabled: boolean;
  cash_rebalance_enabled: boolean;
  auto_rebalance_enabled: boolean;
  min_drift_pct: string;
  min_order_fiat: string;
};

const WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const pad = (n: number) => String(n).padStart(2, "0");

export function ordinal(day: number): string {
  const teens = day % 100 >= 11 && day % 100 <= 13;
  const suffix = teens
    ? "th"
    : (({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[day % 10] ??
      "th");
  return `${day}${suffix}`;
}

// A "YYYY-MM-DD" read in the local zone, never as UTC midnight.
function parseDate(date: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function weekdayName(date: string): string {
  return WEEKDAYS[parseDate(date).getDay()];
}

export function formatRun(at: string): string {
  const run = new Date(at);
  return `${WEEKDAYS[run.getDay()]} ${run.getDate()} ${MONTHS[run.getMonth()]} at ${pad(run.getHours())}:${pad(run.getMinutes())}`;
}

export function startsLater(
  form: CadenceForm<string>,
  nextAt: string | null,
): boolean {
  if (form.kind === "custom" || form.choice === "asap" || nextAt === null) {
    return false;
  }
  return form.date !== localDate(new Date(nextAt));
}

const CUSTOM = "On a custom schedule";

function late(date: Date): string {
  return date.getDate() >= 29 ? " (or the last day of a shorter month)" : "";
}

function investWhen(form: CadenceForm<InvestChoice>): string {
  if (form.kind === "custom") return CUSTOM;
  const date = parseDate(form.date);
  switch (form.choice) {
    case "asap":
      return "Every 15 minutes";
    case "daily":
      return "Every day at 12:00";
    case "weekly":
      return `Every ${WEEKDAYS[date.getDay()]} at 12:00`;
    case "monthly":
      return `On the ${ordinal(date.getDate())} of every month at 12:00${late(date)}`;
  }
}

function rebalanceWhen(form: CadenceForm<RebalanceChoice>): string {
  if (form.kind === "custom") return CUSTOM;
  const date = parseDate(form.date);
  const d = ordinal(date.getDate());
  switch (form.choice) {
    case "monthly":
      return `On the ${d} of every month${late(date)}`;
    case "quarterly":
      return `On the ${d} of every quarter${late(date)}`;
    case "half-yearly":
      return `On the ${d} every six months`;
    case "yearly":
      return `Every year on ${date.getDate()} ${MONTHS[date.getMonth()]}`;
  }
}

export function summarize(input: SummaryInput): string[] {
  const invest = input.invest_cash_enabled
    ? `${investWhen(input.invest)}, free ${input.fiat} is invested ${
        input.cash_rebalance_enabled
          ? "in the most underweight assets first"
          : "toward your targets"
      }.`
    : `Free ${input.fiat} is not invested automatically; you can invest it from Home.`;

  const drift =
    compare(input.min_drift_pct, "0") === 0
      ? "if any asset is off its target"
      : `if any asset has drifted more than ${formatPercent(input.min_drift_pct)}`;
  const then = input.auto_rebalance_enabled
    ? "the portfolio is rebalanced without asking"
    : "a rebalance is proposed for you to approve";
  const sentences = [
    invest,
    `${rebalanceWhen(input.rebalance)}, ${drift}, ${then}.`,
  ];

  if (compare(input.min_order_fiat, "0") > 0) {
    sentences.push(
      `Orders smaller than ${formatMoney(input.min_order_fiat, input.fiat)} are skipped.`,
    );
  }
  return sentences;
}
