import { expect, test } from "@playwright/test";
import { mockApi, type Reply } from "./mockApi.js";

const ME = {
  id: "0b0f6c1e-6a58-4d8a-9d46-3c1f6f0f6b11",
  email: "ada@example.com",
  provider: "google",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const KEY_ACCEPTED = {
  validated_at: "2026-10-20T09:00:00Z",
  permissions: [
    "query-funds",
    "query-open-trades",
    "query-closed-trades",
    "modify-trades",
  ],
  ip_allowlist: ["203.0.113.7"],
  unnecessary: [],
};

const DEFAULT_CONFIG = {
  invest_cash_enabled: false,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "0",
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
  onboarded_at: null,
};

type Config = Record<string, unknown> & { fiat: string };
type Asset = { asset: string; pair: string; target_pct: string };

const HOLDINGS = [
  { asset: "BTC", amount: "1", price: "300", value: "300", weight_pct: "30" },
  { asset: "ETH", amount: "1", price: "600", value: "600", weight_pct: "60" },
];

// The platform's answers, kept in the test: what each write sets and what each
// read returns, as the component tests' fakePlatform does (that one is MSW).
function platform(initial: {
  registered: boolean;
  config: Config | null;
  assets: Asset[];
}) {
  const state = { ...initial };
  const cashTarget = () =>
    String(
      100 - state.assets.reduce((sum, a) => sum + Number(a.target_pct), 0),
    );
  const withSchedule = (config: Config) => ({
    ...config,
    next_invest_at: config.invest_cash_enabled ? "2026-10-26T11:20:00Z" : null,
  });
  const ok = (body: unknown): Reply => ({ status: 200, body });

  const replies = {
    "/api/auth/me": ok(ME),
    "GET /api/config": (): Reply =>
      state.config === null ? { status: 404 } : ok(withSchedule(state.config)),
    "PATCH /api/config": (body: unknown): Reply => {
      const { onboarded, ...fields } = body as Record<string, unknown>;
      state.config = {
        ...DEFAULT_CONFIG,
        ...state.config,
        ...fields,
      } as Config;
      if (onboarded) state.config.onboarded_at = "2026-10-20T10:00:00Z";
      return ok(withSchedule(state.config));
    },
    "GET /api/credentials/status": (): Reply =>
      ok(
        state.registered
          ? { registered: true, validated_at: "2026-10-20T09:00:00Z" }
          : { registered: false },
      ),
    "POST /api/credentials": (): Reply => {
      state.registered = true;
      return { status: 201, body: KEY_ACCEPTED };
    },
    "GET /api/assets": (): Reply =>
      ok({ assets: state.assets, cash_target_pct: cashTarget() }),
    "POST /api/portfolio/refresh": (): Reply => {
      const targetOf = new Map(
        state.assets.map((a) => [a.asset, a.target_pct]),
      );
      return ok({
        as_of: "2026-10-20T10:00:00Z",
        fiat: state.config?.fiat,
        total_value: "1000",
        cash: "100",
        cash_target_pct: cashTarget(),
        cash_weight_pct: null,
        holdings: HOLDINGS.map((h) => ({
          ...h,
          managed: targetOf.has(h.asset),
          locked: false,
          target_pct: targetOf.get(h.asset) ?? null,
        })),
      });
    },
  };
  // PUT /api/assets/{asset} has the asset in its path, so one entry per asset.
  const puts = Object.fromEntries(
    HOLDINGS.map(({ asset }) => [
      `PUT /api/assets/${asset}`,
      (body: unknown): Reply => {
        const stored = {
          asset,
          pair: `${asset}/${state.config?.fiat}`,
          target_pct: String((body as { target_pct: string }).target_pct),
        };
        state.assets = [
          ...state.assets.filter((a) => a.asset !== asset),
          stored,
        ];
        return ok(stored);
      },
    ]),
  );
  return { ...replies, ...puts };
}

test("a new user goes from sign-in to Home through the four steps", async ({
  page,
}) => {
  const calls = await mockApi(
    page,
    platform({ registered: false, config: null, assets: [] }),
  );
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding\/key$/);

  await page.getByLabel("API key").fill("the-key");
  await page.getByLabel("Private key").fill("the-secret");
  await page.getByRole("button", { name: "Verify & save" }).click();
  await expect(page.getByRole("status")).toHaveText("Key saved.");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page).toHaveURL(/\/onboarding\/portfolio$/);
  await page.getByLabel("Currency").selectOption("EUR");
  await page.getByRole("button", { name: "Save currency" }).click();
  const btc = page.getByRole("listitem", { name: "BTC" });
  const eth = page.getByRole("listitem", { name: "ETH" });
  await expect(page.getByLabel("Target for BTC")).toHaveValue("30");
  await expect(page.getByLabel("Target for ETH")).toHaveValue("60");
  await expect(btc).toContainText("€300.00");
  await expect(eth).toContainText("€600.00");
  await expect(page.getByText("Cash (EUR) target: 10 %")).toBeVisible();
  await page.getByRole("button", { name: "Save targets" }).click();

  await expect(page).toHaveURL(/\/onboarding\/automation$/);
  await page.getByLabel("Invest cadence").selectOption("Weekly");
  await page
    .getByRole("switch", { name: "Invest free cash automatically" })
    .click();
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page).toHaveURL(/\/onboarding\/summary$/);
  await expect(
    page.getByText("free EUR is invested toward your targets"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  expect(calls.filter((call) => !call.startsWith("GET "))).toEqual([
    "POST /api/credentials",
    "PATCH /api/config",
    "POST /api/portfolio/refresh",
    "PUT /api/assets/BTC",
    "PUT /api/assets/ETH",
    "PATCH /api/config",
    "PATCH /api/config",
  ]);
});

test("a reload in the middle resumes at the same step", async ({ page }) => {
  await mockApi(
    page,
    platform({
      registered: true,
      config: { ...DEFAULT_CONFIG, fiat: "EUR" },
      assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
    }),
  );
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/onboarding\/automation$/);
  await expect(page.getByRole("heading", { name: "Automation" })).toBeVisible();
});
