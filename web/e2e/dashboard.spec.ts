import { expect, test } from "@playwright/test";
import { mockApi, type Reply } from "./mockApi.js";

const ME = {
  id: "0b0f6c1e-6a58-4d8a-9d46-3c1f6f0f6b11",
  email: "ada@example.com",
  provider: "google",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const CONFIG = {
  fiat: "EUR",
  invest_cash_enabled: false,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "2",
  min_order_fiat: "0",
  invest_cadence_mode: "MIN",
  invest_interval_days: null,
  invest_interval_months: null,
  invest_cadence_anchor: null,
  rebalance_cadence_mode: "MIN",
  rebalance_interval_days: null,
  rebalance_interval_months: null,
  rebalance_cadence_anchor: null,
  next_invest_at: null,
  next_rebalance_at: "2026-11-01T11:20:00Z",
  onboarded_at: "2026-10-01T00:00:00Z",
};

const SNAPSHOT = {
  as_of: "2026-10-20T10:00:00Z",
  fiat: "EUR",
  total_value: "1000",
  cash: "100",
  cash_target_pct: "10",
  cash_weight_pct: "10",
  holdings: [
    {
      asset: "BTC",
      amount: "1",
      price: "325",
      value: "325",
      weight_pct: "32.5",
      managed: true,
      locked: false,
      target_pct: "30",
    },
    {
      asset: "ETH",
      amount: "1",
      price: "575",
      value: "575",
      weight_pct: "57.5",
      managed: true,
      locked: false,
      target_pct: "60",
    },
  ],
};

function proposalLeg(asset: string, side: string) {
  return {
    asset,
    pair: `${asset}/EUR`,
    side,
    amount_fiat: "25",
    minimum_fiat: null,
    note: null,
  };
}

const PROPOSAL = {
  version: 1,
  status: "LIVE",
  trigger: "MANUAL",
  fiat: "EUR",
  updated_at: "2026-10-20T10:00:00Z",
  legs: [proposalLeg("BTC", "sell"), proposalLeg("ETH", "buy")],
};

function filledLeg(asset: string, side: string, amount: string) {
  return {
    asset,
    pair: `${asset}/EUR`,
    side,
    amount_fiat: amount,
    minimum_fiat: null,
    status: "FILLED",
    cl_ord_id: null,
    txid: null,
    cost: null,
    executed_volume: null,
    executed_price: null,
    fee: null,
    error: null,
    note: null,
    volume: null,
  };
}

const ok = (body: unknown): Reply => ({ status: 200, body });

function onboarded() {
  return {
    "/api/auth/me": ok(ME),
    "GET /api/config": ok(CONFIG),
    "GET /api/portfolio": ok(SNAPSHOT),
  };
}

test("an onboarded user reads the account, requests a rebalance and approves it", async ({
  page,
}) => {
  // The proposal exists once the rebalance was requested, and not after
  // it was approved.
  const state: { proposal: typeof PROPOSAL | null } = { proposal: null };
  const calls = await mockApi(page, {
    ...onboarded(),
    "GET /api/proposal": (): Reply =>
      state.proposal === null
        ? { status: 404, body: { detail: "there is no live proposal" } }
        : ok(state.proposal),
    "POST /api/rebalance": (): Reply => {
      state.proposal = PROPOSAL;
      return ok({
        status: "PROPOSED",
        legs: [],
        proposal: PROPOSAL,
        messages: [],
      });
    },
    "POST /api/proposal/approve": (): Reply => {
      state.proposal = null;
      return ok({
        status: "DONE",
        legs: [filledLeg("BTC", "sell", "25"), filledLeg("ETH", "buy", "25")],
        proposal: null,
        messages: [],
      });
    },
    "POST /api/portfolio/refresh": ok(SNAPSHOT),
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText("€1,000.00", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("listitem", { name: "BTC" }).getByText("+2.5 pts"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Rebalance now" }).click();
  await expect(page).toHaveURL(/\/proposal$/);
  await expect(page.getByText("Sell BTC for €25.00")).toBeVisible();
  await expect(page.getByText("Buy ETH for €25.00")).toBeVisible();

  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Every order was filled.")).toBeVisible();

  const sent = calls.filter((call) => !call.startsWith("GET "));
  expect(sent).toEqual([
    "POST /api/rebalance",
    "POST /api/proposal/approve",
    "POST /api/portfolio/refresh",
  ]);
});

test("invest now shows the orders before it sends them", async ({ page }) => {
  // The mock's call log drops the query string; this one keeps it.
  const invests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/invest") {
      invests.push(url.search);
    }
  });
  const leg = { ...filledLeg("ETH", "buy", "100"), status: "VALIDATED" };
  await mockApi(page, {
    ...onboarded(),
    "GET /api/proposal": { status: 404, body: { detail: "no proposal" } },
    // The first POST is the preview, the second sends.
    "POST /api/invest": (): Reply =>
      invests.length === 1
        ? ok({ status: "PREVIEW", preview: true, legs: [leg], messages: [] })
        : ok({
            status: "DONE",
            preview: false,
            legs: [filledLeg("ETH", "buy", "100")],
            messages: [],
          }),
    "POST /api/portfolio/refresh": ok(SNAPSHOT),
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Invest now" }).click();
  await expect(page.getByText("Buy ETH for €100.00")).toBeVisible();
  expect(invests).toEqual(["?preview=true"]);

  await page.getByRole("button", { name: "Confirm: invest €100.00" }).click();
  await expect(page.getByText("Every order was filled.")).toBeVisible();
  expect(invests).toEqual(["?preview=true", ""]);
});
