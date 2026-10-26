import { expect, test } from "vitest";
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
