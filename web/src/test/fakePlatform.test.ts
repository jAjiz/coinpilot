import { afterEach, expect, test, vi } from "vitest";
import { fakePlatform } from "./fakePlatform";
import { server } from "./server";

async function call(
  platform: ReturnType<typeof fakePlatform>,
  method: string,
  path: string,
  body?: unknown,
) {
  server.use(...platform.handlers);
  const response = await fetch(new URL(path, window.location.origin), {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: { "content-type": "application/json" },
  });
  const text = await response.text();
  return {
    status: response.status,
    body: text ? JSON.parse(text) : null,
  };
}

const eur = { fiat: "EUR" };

test("asset writes need settings, then follow the platform's checks", async () => {
  const p = fakePlatform();
  expect(await call(p, "PUT", "/api/assets/BTC", { target_pct: "10" })).toEqual(
    {
      status: 409,
      body: { detail: "choose a fiat with PATCH /api/config first" },
    },
  );
  await call(p, "PATCH", "/api/config", eur);
  p.state.untradable = ["XYZ"];
  expect(
    (await call(p, "PUT", "/api/assets/XYZ", { target_pct: "999" })).body,
  ).toEqual({ detail: "kraken has no tradable XYZ/EUR pair" });
  await call(p, "PUT", "/api/assets/ETH", { target_pct: "60" });
  expect(await call(p, "PUT", "/api/assets/BTC", { target_pct: "50" })).toEqual(
    {
      status: 422,
      body: { detail: "the weights would sum to 110; the limit is 100" },
    },
  );
});

test("assets come sorted by code and an update keeps its place", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  await call(p, "PUT", "/api/assets/ETH", { target_pct: "30" });
  await call(p, "PUT", "/api/assets/BTC", { target_pct: "40" });
  await call(p, "PUT", "/api/assets/BTC", { target_pct: "50" });
  const { body } = await call(p, "GET", "/api/assets");
  expect(body.assets.map((a: { asset: string }) => a.asset)).toEqual([
    "BTC",
    "ETH",
  ]);
  expect(body.cash_target_pct).toBe("20");
});

test("deleting an asset without a weight is a 404", async () => {
  const p = fakePlatform();
  expect(await call(p, "DELETE", "/api/assets/BTC")).toEqual({
    status: 404,
    body: { detail: "that asset has no weight" },
  });
});

test("the fiat cannot be changed, but may be repeated", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  expect(await call(p, "PATCH", "/api/config", eur)).toMatchObject({
    status: 200,
  });
  expect(await call(p, "PATCH", "/api/config", { fiat: "USD" })).toEqual({
    status: 422,
    body: { detail: "the fiat cannot be changed" },
  });
});

test("a field sent as null is cleared, as the real route does", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  await call(p, "PATCH", "/api/config", {
    invest_interval_days: 1,
    invest_interval_months: null,
  });
  const daily = await call(p, "PATCH", "/api/config", {});
  expect(daily.body.invest_interval_days).toBe(1);
  const monthly = await call(p, "PATCH", "/api/config", {
    invest_interval_days: null,
    invest_interval_months: 1,
  });
  expect(monthly.body.invest_interval_days).toBeNull();
  expect(monthly.body.invest_interval_months).toBe(1);
  expect((await call(p, "GET", "/api/config")).body).toMatchObject({
    invest_interval_days: null,
    invest_interval_months: 1,
  });
});

test("a refresh reports the cash target left by the stored targets", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  await call(p, "PUT", "/api/assets/BTC", { target_pct: "70" });
  const { body } = await call(p, "POST", "/api/portfolio/refresh");
  expect(body.cash_target_pct).toBe("30");
  expect(p.requests.at(-1)?.path).toBe("/api/portfolio/refresh");
});

test("the snapshot and the proposal answer 404 until there is one", async () => {
  const p = fakePlatform();
  expect(await call(p, "GET", "/api/portfolio")).toEqual({
    status: 404,
    body: {
      detail: "no snapshot yet; POST /api/portfolio/refresh to take one",
    },
  });
  expect(await call(p, "GET", "/api/proposal")).toEqual({
    status: 404,
    body: { detail: "there is no live proposal" },
  });
});

test("a refresh becomes the snapshot that GET /api/portfolio returns", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  const refreshed = await call(p, "POST", "/api/portfolio/refresh");
  expect(await call(p, "GET", "/api/portfolio")).toEqual({
    status: 200,
    body: refreshed.body,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

test("lifting a pause moves both next runs to the first slot after now", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-27T08:00:00Z"));
  const p = fakePlatform({
    config: {
      fiat: "EUR",
      paused: true,
      invest_cash_enabled: true,
      rebalance_cadence_mode: "INTERVAL",
      rebalance_interval_days: 7,
      rebalance_interval_months: null,
      rebalance_cadence_anchor: "2026-10-01T11:00:00Z",
    } as never,
    // Both fell behind while paused.
    nextInvestAt: "2026-10-20T11:20:00Z",
    nextRebalanceAt: "2026-10-22T11:00:00Z",
  });

  const { body } = await call(p, "PATCH", "/api/config", { paused: false });

  expect(body.next_invest_at).toBe("2026-10-27T11:20:00.000Z");
  expect(body.next_rebalance_at).toBe("2026-10-29T11:00:00.000Z");
});

test("a run still ahead is left where it is by a change that reschedules", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-27T08:00:00Z"));
  const p = fakePlatform({
    config: { fiat: "EUR", paused: false, invest_cash_enabled: true } as never,
    nextInvestAt: "2026-10-30T11:20:00Z",
  });

  const { body } = await call(p, "PATCH", "/api/config", { paused: true });

  expect(body.next_invest_at).toBe("2026-10-30T11:20:00Z");
});

test("dismissing the proposal without a version is a 422", async () => {
  const p = fakePlatform({
    proposal: { version: 3 } as never,
  });

  const { status } = await call(p, "DELETE", "/api/proposal");

  expect(status).toBe(422);
  expect(p.state.proposal).not.toBeNull();
});

test("orders without a session are newest first, a session's oldest first", async () => {
  const order = (id: string, created_at: string, session_id: string) =>
    ({ cl_ord_id: id, created_at, session_id }) as never;
  const p = fakePlatform({
    orders: [
      order("a", "2026-10-20T10:00:00Z", "s1"),
      order("b", "2026-10-21T10:00:00Z", "s1"),
      order("c", "2026-10-22T10:00:00Z", "s2"),
    ],
  });

  const all = await call(p, "GET", "/api/orders");
  const one = await call(p, "GET", "/api/orders?session=s1");

  expect(all.body.map((o: { cl_ord_id: string }) => o.cl_ord_id)).toEqual([
    "c",
    "b",
    "a",
  ]);
  expect(one.body.map((o: { cl_ord_id: string }) => o.cl_ord_id)).toEqual([
    "a",
    "b",
  ]);
});
