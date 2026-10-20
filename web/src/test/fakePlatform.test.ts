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

test("a refresh reports the cash target left by the stored targets", async () => {
  const p = fakePlatform();
  await call(p, "PATCH", "/api/config", eur);
  await call(p, "PUT", "/api/assets/BTC", { target_pct: "70" });
  const { body } = await call(p, "POST", "/api/portfolio/refresh");
  expect(body.cash_target_pct).toBe("30");
  expect(p.requests.at(-1)?.path).toBe("/api/portfolio/refresh");
});
