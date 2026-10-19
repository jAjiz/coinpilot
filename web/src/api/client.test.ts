import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { server } from "@/test/server";
import { ApiError, api, onSessionEnded, unwrap } from "./client";

let refreshCalls = 0;
let refreshed = false;
const unsubscribers: Array<() => void> = [];

beforeEach(() => {
  refreshCalls = 0;
  refreshed = false;
});
afterEach(() => {
  unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe());
});

function refreshAnswers(status: 200 | 401) {
  return http.post("/api/auth/refresh", async () => {
    refreshCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, 20));
    if (status === 401) {
      return HttpResponse.json({ detail: "refresh refused" }, { status: 401 });
    }
    refreshed = true;
    return HttpResponse.json({ access_token: "a", refresh_token: "r" });
  });
}

function expiredUntilRefresh(path: string, body: object) {
  return http.get(path, () =>
    refreshed
      ? HttpResponse.json(body)
      : HttpResponse.json({ detail: "expired" }, { status: 401 }),
  );
}

test("three requests that meet a 401 share one refresh and all succeed", async () => {
  server.use(
    refreshAnswers(200),
    expiredUntilRefresh("/api/auth/me", { id: 1 }),
    expiredUntilRefresh("/api/config", { paused: false }),
    expiredUntilRefresh("/api/credentials/status", { registered: true }),
  );

  const results = await Promise.all([
    api.GET("/api/auth/me"),
    api.GET("/api/config"),
    api.GET("/api/credentials/status"),
  ]);

  expect(results.map((r) => r.response.status)).toEqual([200, 200, 200]);
  expect(refreshCalls).toBe(1);
});

test("a refused refresh ends the session once and returns the 401", async () => {
  const ended = vi.fn();
  unsubscribers.push(onSessionEnded(ended));
  server.use(
    refreshAnswers(401),
    expiredUntilRefresh("/api/auth/me", {}),
    expiredUntilRefresh("/api/config", {}),
    expiredUntilRefresh("/api/credentials/status", {}),
  );

  const results = await Promise.all([
    api.GET("/api/auth/me"),
    api.GET("/api/config"),
    api.GET("/api/credentials/status"),
  ]);

  expect(results.map((r) => r.response.status)).toEqual([401, 401, 401]);
  expect(refreshCalls).toBe(1);
  expect(ended).toHaveBeenCalledTimes(1);
});

test("a retried request is sent again with its body", async () => {
  const bodies: unknown[] = [];
  server.use(
    refreshAnswers(200),
    http.patch("/api/config", async ({ request }) => {
      bodies.push(await request.json());
      return refreshed
        ? HttpResponse.json({ paused: true })
        : HttpResponse.json({ detail: "expired" }, { status: 401 });
    }),
  );

  const { response } = await api.PATCH("/api/config", {
    body: { paused: true },
  });

  expect(response.status).toBe(200);
  expect(bodies).toEqual([{ paused: true }, { paused: true }]);
});

test("a second 401 after the retry is returned, not refreshed again", async () => {
  server.use(
    refreshAnswers(200),
    http.get("/api/config", () =>
      HttpResponse.json({ detail: "still no" }, { status: 401 }),
    ),
  );

  const { response } = await api.GET("/api/config");

  expect(response.status).toBe(401);
  expect(refreshCalls).toBe(1);
});

test("other errors pass through without a refresh", async () => {
  server.use(
    refreshAnswers(200),
    http.get("/api/config", () =>
      HttpResponse.json({ detail: "down" }, { status: 503 }),
    ),
  );

  const { response } = await api.GET("/api/config");

  expect(response.status).toBe(503);
  expect(refreshCalls).toBe(0);
});

test("unwrap throws the platform's detail", async () => {
  server.use(
    http.get("/api/credentials/status", () =>
      HttpResponse.json({ detail: "no key is registered" }, { status: 404 }),
    ),
    http.patch("/api/config", () =>
      HttpResponse.json(
        {
          detail: [
            {
              loc: ["body", "x"],
              msg: "Input should be greater than 0",
              type: "greater_than",
            },
          ],
        },
        { status: 422 },
      ),
    ),
  );

  const notFound = await unwrap(api.GET("/api/credentials/status")).catch(
    (e: unknown) => e,
  );
  expect(notFound).toBeInstanceOf(ApiError);
  expect(notFound).toMatchObject({
    status: 404,
    detail: "no key is registered",
  });

  const invalid = await unwrap(
    api.PATCH("/api/config", { body: { paused: true } }),
  ).catch((e: unknown) => e);
  expect(invalid).toMatchObject({
    status: 422,
    detail: "Input should be greater than 0",
  });
});

test("a non-JSON failure with no status text still has a message", async () => {
  // HTTP/2 carries no reason phrase, so statusText is empty.
  const response = new Response("<html>Bad Gateway</html>", {
    status: 502,
    headers: { "Content-Type": "text/html" },
  });
  expect(response.statusText).toBe("");
  const error = await unwrap(
    Promise.resolve({ error: "<html>Bad Gateway</html>", response }),
  ).catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).message).toBe("The platform answered 502.");
});
