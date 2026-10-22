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
