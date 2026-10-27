import { expect, test } from "@playwright/test";
import { mockApi, nextRun, type Reply } from "./mockApi.js";

const ME = {
  id: "0b0f6c1e-6a58-4d8a-9d46-3c1f6f0f6b11",
  email: "ada@example.com",
  provider: "google",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const CONFIG: Record<string, unknown> = {
  fiat: "EUR",
  invest_cash_enabled: true,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "2",
  min_order_fiat: "0",
  invest_cadence_mode: "INTERVAL",
  invest_interval_days: 7,
  invest_interval_months: null,
  invest_cadence_anchor: "2026-10-26T11:00:00Z",
  rebalance_cadence_mode: "MIN",
  rebalance_interval_days: null,
  rebalance_interval_months: null,
  rebalance_cadence_anchor: null,
  next_invest_at: "2030-01-07T11:00:00Z",
  next_rebalance_at: "2030-02-01T11:20:00Z",
  onboarded_at: "2026-10-01T00:00:00Z",
};

const SESSION_ID = "5d0c1f3e-1b0a-4c55-8a7e-0a1b2c3d4e5f";

const SESSIONS = [
  {
    id: SESSION_ID,
    started_at: "2026-10-20T10:00:00Z",
    finished_at: "2026-10-20T10:00:05Z",
    duration_ms: 5000,
    status: "DONE",
    operation: "INVEST",
    trigger: "SCHEDULER",
    log_messages: null,
  },
];

const ORDERS = [
  {
    cl_ord_id: "cl-1",
    session_id: SESSION_ID,
    txid: "TX1",
    pair: "BTC/EUR",
    asset: "BTC",
    side: "buy",
    reason: "INVEST",
    status: "FILLED",
    requested_fiat: "25",
    executed_volume: "0.001",
    executed_price: "24950",
    fee: "0.06",
    cost: "24.95",
    error: null,
    created_at: "2026-10-20T10:00:02Z",
  },
];

const ok = (body: unknown): Reply => ({ status: 200, body });

function signedIn() {
  return {
    "/api/auth/me": ok(ME),
    "GET /api/portfolio": { status: 404, body: { detail: "no snapshot" } },
    "GET /api/proposal": { status: 404, body: { detail: "no proposal" } },
    "GET /api/credentials/status": ok({
      registered: true,
      validated_at: "2026-10-20T09:00:00Z",
      key_version: 1,
    }),
    "GET /api/assets": ok({
      assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "60" }],
      cash_target_pct: "40",
    }),
  };
}

// The app's formatRun, in the time zone the tests run in (Europe/Madrid).
function formatRun(at: string): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Madrid",
      weekday: "long",
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(at))
      .map((p) => [p.type, p.value]),
  );
  return `${parts.weekday} ${parts.day} ${parts.month} at ${parts.hour}:${parts.minute}`;
}

test("a cadence changed in settings moves the next run", async ({ page }) => {
  const state = { config: { ...CONFIG } };
  const patches: Record<string, unknown>[] = [];
  await mockApi(page, {
    ...signedIn(),
    "GET /api/config": () => ok(state.config),
    "PATCH /api/config": (body): Reply => {
      patches.push(body as Record<string, unknown>);
      const merged = { ...state.config, ...(body as object) };
      merged.next_invest_at = nextRun(
        merged,
        "invest",
        state.config.next_invest_at as string,
      );
      merged.next_rebalance_at = nextRun(
        merged,
        "rebalance",
        state.config.next_rebalance_at as string,
      );
      state.config = merged;
      return ok(merged);
    },
  });

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  const next = page.getByText(/^Next invest:/);
  await expect(next).toContainText("Monday 7 January");
  await page.getByRole("button", { name: "Edit automation" }).click();
  await page.getByLabel("Invest cadence").selectOption("monthly");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(
    page.getByRole("button", { name: "Edit automation" }),
  ).toBeVisible();

  expect(patches).toHaveLength(1);
  expect(patches[0]).toMatchObject({
    invest_cadence_mode: "INTERVAL",
    invest_interval_months: 1,
    invest_interval_days: null,
  });
  const expected = nextRun(state.config, "invest", null);
  expect(expected).not.toBeNull();
  await expect(next).toHaveText(`Next invest: ${formatRun(expected!)}`);
});

test("history shows a run and its orders", async ({ page }) => {
  await mockApi(page, {
    ...signedIn(),
    "GET /api/config": ok(CONFIG),
    "GET /api/sessions": ok(SESSIONS),
    "GET /api/orders": ok(ORDERS),
  });

  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await expect(page.getByText("Nothing to do")).toHaveCount(0);
  await page.getByRole("button", { name: /Invest · scheduled/ }).click();
  await expect(page.getByText("Filled", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Cost .* · fee /)).toBeVisible();
});

test("sign out lands on the sign-in page", async ({ page }) => {
  const state = { signedIn: true };
  const calls = await mockApi(page, {
    ...signedIn(),
    "/api/auth/me": (): Reply =>
      state.signedIn
        ? ok(ME)
        : { status: 401, body: { detail: "not signed in" } },
    "POST /api/auth/refresh": { status: 401, body: { detail: "refused" } },
    "POST /api/auth/logout": (): Reply => {
      state.signedIn = false;
      return { status: 204 };
    },
    "GET /api/config": ok(CONFIG),
  });

  await page.goto("/settings");
  await expect(page.getByText("Signed in as ada@example.com.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(calls).toContain("POST /api/auth/logout");
});
