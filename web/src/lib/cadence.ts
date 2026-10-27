import type { components } from "@/api/schema";

type ConfigOut = components["schemas"]["ConfigOut"];
type ConfigPatch = components["schemas"]["ConfigPatch"];

// Translates the onboarding form's cadence choices to and from the platform's
// cadence fields. Times are the browser's zone: the anchor is the chosen date
// at 12:00 local, sent as a UTC instant.

export type InvestChoice = "asap" | "daily" | "weekly" | "monthly";
export type RebalanceChoice =
  "monthly" | "quarterly" | "half-yearly" | "yearly";
export type CadenceFields = {
  mode: "MIN" | "INTERVAL";
  interval_days: number | null;
  interval_months: number | null;
  cadence_anchor: string | null;
};
export type CadenceForm<C> =
  | { kind: "choice"; choice: C; date: string }
  | { kind: "custom"; fields: CadenceFields };

type Length = { days: number; months: number };

const INVEST: Record<Exclude<InvestChoice, "asap">, Length> = {
  daily: { days: 1, months: 0 },
  weekly: { days: 7, months: 0 },
  monthly: { days: 0, months: 1 },
};

const REBALANCE: Record<RebalanceChoice, Length> = {
  monthly: { days: 0, months: 1 },
  quarterly: { days: 0, months: 3 },
  "half-yearly": { days: 0, months: 6 },
  yearly: { days: 0, months: 12 },
};

const pad = (n: number, width = 2) => String(n).padStart(width, "0");

export function localDate(at: Date): string {
  return `${pad(at.getFullYear(), 4)}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

// A date the form can send: a real YYYY-MM-DD day with a year from 2000 to 9999.
export function isUsableDate(date: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (match === null || Number(match[1]) < 2000) return false;
  const [y, m, d] = match.slice(1).map(Number);
  // new Date() rolls an impossible day (02-31) over into the next month.
  return localDate(new Date(y, m - 1, d)) === date;
}

export function localNoon(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d, 12).toISOString();
}

function interval({ days, months }: Length, date: string): CadenceFields {
  return {
    mode: "INTERVAL",
    interval_days: days || null,
    interval_months: months || null,
    cadence_anchor: localNoon(date),
  };
}

export function investFields(
  choice: InvestChoice,
  date: string,
): CadenceFields {
  if (choice === "asap") {
    return {
      mode: "MIN",
      interval_days: null,
      interval_months: null,
      cadence_anchor: null,
    };
  }
  return interval(INVEST[choice], date);
}

export function rebalanceFields(
  choice: RebalanceChoice,
  date: string,
): CadenceFields {
  return interval(REBALANCE[choice], date);
}

// The anchor's local date, when the anchor is exactly 12:00:00.000 local.
function noonDate(anchor: string | null): string | null {
  if (anchor === null) return null;
  const at = new Date(anchor);
  if (Number.isNaN(at.getTime())) return null;
  const onTheHour =
    at.getHours() === 12 &&
    at.getMinutes() === 0 &&
    at.getSeconds() === 0 &&
    at.getMilliseconds() === 0;
  return onTheHour ? localDate(at) : null;
}

function readInterval<C extends string>(
  fields: CadenceFields,
  table: Record<C, Length>,
): CadenceForm<C> {
  const date = noonDate(fields.cadence_anchor);
  if (fields.mode !== "INTERVAL" || date === null) {
    return { kind: "custom", fields };
  }
  const days = fields.interval_days ?? 0;
  const months = fields.interval_months ?? 0;
  for (const choice of Object.keys(table) as C[]) {
    if (table[choice].days === days && table[choice].months === months) {
      return { kind: "choice", choice, date };
    }
  }
  return { kind: "custom", fields };
}

// The anchor as a datetime-local input shows it: local time, to the minute.
export function anchorInput(iso: string | null): string {
  if (iso === null) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return `${localDate(at)}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

// The UTC instant of a local date-time; null when it is not a usable one.
export function anchorFromInput(text: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(text);
  if (match === null || !isUsableDate(match[1])) return null;
  const [y, m, d] = match[1].split("-").map(Number);
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  if (hour > 23 || minute > 59) return null;
  return new Date(y, m - 1, d, hour, minute).toISOString();
}

export type CustomErrors = {
  days: string | null;
  months: string | null;
  anchor: string | null;
};

const whole = (n: number | null, max: number) =>
  n === null || (Number.isInteger(n) && n >= 0 && n <= max);

// The bounds ConfigPatch enforces: 0-3650 days, 0-120 months. A mode of MIN
// uses neither, so nothing is checked.
export function checkCustom(fields: CadenceFields): CustomErrors {
  const none = { days: null, months: null, anchor: null };
  if (fields.mode === "MIN") return none;
  const days = whole(fields.interval_days, 3650)
    ? null
    : "Enter whole days from 0 to 3650.";
  const months = whole(fields.interval_months, 120)
    ? null
    : "Enter whole months from 0 to 120.";
  return {
    days:
      days ??
      (months === null &&
      !(fields.interval_days ?? 0) &&
      !(fields.interval_months ?? 0)
        ? "Choose at least one day or one month."
        : null),
    months,
    anchor: fields.cadence_anchor === null ? "Choose when it starts." : null,
  };
}

export function sameFields(a: CadenceFields, b: CadenceFields): boolean {
  return (
    a.mode === b.mode &&
    a.interval_days === b.interval_days &&
    a.interval_months === b.interval_months &&
    a.cadence_anchor === b.cadence_anchor
  );
}

export function readInvest(
  fields: CadenceFields,
  today: string,
): CadenceForm<InvestChoice> {
  if (fields.mode === "MIN")
    return { kind: "choice", choice: "asap", date: today };
  return readInterval(fields, INVEST);
}

export function readRebalance(
  fields: CadenceFields,
): CadenceForm<RebalanceChoice> {
  return readInterval(fields, REBALANCE);
}

export function cadenceOf(
  config: ConfigOut,
  prefix: "invest" | "rebalance",
): CadenceFields {
  return {
    mode: config[`${prefix}_cadence_mode`],
    interval_days: config[`${prefix}_interval_days`],
    interval_months: config[`${prefix}_interval_months`],
    cadence_anchor: config[`${prefix}_cadence_anchor`],
  };
}

export function cadencePatch(
  prefix: "invest" | "rebalance",
  fields: CadenceFields,
): ConfigPatch {
  return {
    [`${prefix}_cadence_mode`]: fields.mode,
    [`${prefix}_interval_days`]: fields.interval_days,
    [`${prefix}_interval_months`]: fields.interval_months,
    [`${prefix}_cadence_anchor`]: fields.cadence_anchor,
  };
}
