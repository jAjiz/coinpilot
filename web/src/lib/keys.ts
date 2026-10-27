export const REQUIRED_PERMISSIONS: { code: string; label: string }[] = [
  { code: "query-funds", label: "Query Funds" },
  { code: "query-open-trades", label: "Query Open Orders & Trades" },
  { code: "query-closed-trades", label: "Query Closed Orders & Trades" },
  { code: "modify-trades", label: "Create & Modify Orders" },
];

function codes(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : "";
}

// The platform's 422 for a refused key carries an object, not a string.
export function refusalMessage(detail: unknown): string | null {
  if (typeof detail !== "object" || detail === null) return null;
  const refusal = detail as Record<string, unknown>;
  switch (refusal.rejection) {
    case "invalid_key":
      return "Kraken did not accept this key. Check that both fields were copied in full.";
    case "missing_permissions":
      return `The key is missing these permissions: ${codes(refusal.missing)}.`;
    case "forbidden_permissions":
      return `The key can move funds out of the account (${codes(refusal.forbidden)}). Create a new key without them.`;
    default:
      return null;
  }
}

// "20 October 2026", in the browser's time zone; null when the key was never verified.
export function verifiedOn(
  validatedAt: string | null | undefined,
): string | null {
  return validatedAt
    ? new Date(validatedAt).toLocaleDateString("en-GB", { dateStyle: "long" })
    : null;
}
