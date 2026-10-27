import type { Page } from "@playwright/test";

export type Reply = { status: number; body?: unknown };
// A reply function receives the request's parsed JSON body (null if none).
export type Replies = Record<string, Reply | ((body: unknown) => Reply)>;

// Answers every /api request; an unlisted route is a 404, so a request the
// test did not expect fails loudly instead of reaching anything. A key is a
// path ("/api/config") or a method and a path ("PATCH /api/config"); the
// second wins. Returns the requests seen, as "METHOD /path".
export async function mockApi(page: Page, replies: Replies) {
  const calls: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const call = `${request.method()} ${path}`;
    calls.push(call);
    const entry = replies[call] ?? replies[path];
    const text = request.postData();
    const body: unknown =
      text === null || text === "" ? null : JSON.parse(text);
    const reply = typeof entry === "function" ? entry(body) : entry;
    await route.fulfill({
      status: reply?.status ?? 404,
      contentType: "application/json",
      body: JSON.stringify(reply?.body ?? { detail: "not mocked" }),
    });
  });
  return calls;
}

type Cadence = Record<string, unknown>;

// The first run after now: the anchor, stepped by the interval until it is in
// the future, as the platform reschedules a changed cadence. A MIN cadence
// keeps the time it had (the unit tests' fake platform does the same).
export function nextRun(
  config: Cadence,
  prefix: "invest" | "rebalance",
  current: string | null,
): string | null {
  const anchor = config[`${prefix}_cadence_anchor`];
  if (config[`${prefix}_cadence_mode`] !== "INTERVAL" || !anchor) {
    return current;
  }
  const days = Number(config[`${prefix}_interval_days`] ?? 0);
  const months = Number(config[`${prefix}_interval_months`] ?? 0);
  if (days === 0 && months === 0) return current;
  const at = new Date(String(anchor));
  while (at.getTime() <= Date.now()) {
    at.setUTCDate(at.getUTCDate() + days);
    at.setUTCMonth(at.getUTCMonth() + months);
  }
  return at.toISOString();
}
