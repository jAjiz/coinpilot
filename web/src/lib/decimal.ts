import Big from "big.js";

// Amounts and percentages are decimal strings, never numbers (spec §4.5).

export function parseDecimal(text: string, places: number): string | null {
  const match = /^(\d+)(?:[.,](\d+))?$/.exec(text.trim());
  if (match === null) return null;
  if ((match[2] ?? "").length > places) return null;
  return canonical(Big(`${match[1]}.${match[2] ?? "0"}`));
}

function canonical(value: Big): string {
  // toFixed() never uses exponent notation, unlike toString().
  const fixed = value.toFixed();
  return fixed === "-0" ? "0" : fixed;
}

export function sum(values: string[]): string {
  return canonical(values.reduce((acc, v) => acc.plus(v), Big(0)));
}

export function subtract(a: string, b: string): string {
  return canonical(Big(a).minus(b));
}

export function compare(a: string, b: string): -1 | 0 | 1 {
  return Big(a).cmp(b) as -1 | 0 | 1;
}

export function formatMoney(value: string, fiat: string): string {
  const format = new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: fiat,
    currencyDisplay: "narrowSymbol",
  });
  // Intl formats a decimal string exactly; Number(value) would lose digits.
  return format.format(value as unknown as number);
}

export function formatPercent(value: string): string {
  return `${canonical(Big(value))} %`;
}
