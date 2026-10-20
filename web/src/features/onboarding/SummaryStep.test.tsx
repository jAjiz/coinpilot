import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

const CONFIG: Config = {
  fiat: "EUR",
  invest_cash_enabled: true,
  cash_rebalance_enabled: true,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "1",
  min_order_fiat: "10",
  invest_cadence_mode: "INTERVAL",
  invest_interval_days: 7,
  invest_interval_months: null,
  invest_cadence_anchor: "2026-10-26T11:00:00.000Z",
  rebalance_cadence_mode: "INTERVAL",
  rebalance_interval_days: null,
  rebalance_interval_months: 3,
  rebalance_cadence_anchor: "2026-11-01T11:00:00.000Z",
  next_invest_at: null,
  next_rebalance_at: null,
  onboarded_at: null,
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-20T08:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

function platform(
  config: Partial<Config> = {},
  initial: Partial<FakeState> = {},
) {
  return fakePlatform({
    registered: true,
    config: { ...CONFIG, ...config },
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "50" }],
    nextInvestAt: "2026-10-26T10:37:00Z",
    nextRebalanceAt: "2026-11-01T11:00:00Z",
    ...initial,
  });
}

async function open(fake = platform()) {
  const router = renderAt("/onboarding/summary", fake.handlers);
  await screen.findByText(/This is what CoinPilot will do/);
  return router;
}

const start = () => screen.getByRole("button", { name: "Start" });

test("the configuration is told in sentences", async () => {
  await open();
  expect(
    screen.getByText(
      "Every Monday at 12:00, free EUR is invested in the most underweight assets first.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "On the 1st of every quarter, if any asset has drifted more than 1 %, a rebalance is proposed for you to approve.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "This is what CoinPilot will do. Nothing is traded until then.",
    ),
  ).toBeInTheDocument();
});

test("the first runs are shown in local time", async () => {
  await open();
  expect(
    screen.getByText("First investment: Monday 26 October at 11:37"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("First rebalance check: Sunday 1 November at 12:00"),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/The start date has passed/),
  ).not.toBeInTheDocument();
});

test("invest off shows no first investment", async () => {
  await open(platform({ invest_cash_enabled: false }));
  expect(screen.queryByText(/First investment/)).not.toBeInTheDocument();
  expect(screen.getByText(/First rebalance check/)).toBeInTheDocument();
});

test("a start today after noon says the first run is the next one", async () => {
  vi.setSystemTime(new Date("2026-10-20T14:00:00Z"));
  await open(
    platform(
      { invest_cadence_anchor: "2026-10-20T10:00:00.000Z" },
      { nextInvestAt: "2026-10-27T11:00:00Z" },
    ),
  );
  expect(
    screen.getByText("First investment: Tuesday 27 October at 12:00"),
  ).toBeInTheDocument();
  expect(
    screen.getAllByText(
      "The start date has passed, so the first run is the next one.",
    ),
  ).toHaveLength(1);
});

test("Start finishes onboarding and opens Home", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = await open(fake);
  await user.click(start());
  await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  expect(
    await screen.findByRole("heading", { name: "Home" }),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([
    { method: "PATCH", path: "/api/config", body: { onboarded: true } },
  ]);
});

test("Start is disabled while it is sent", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const router = renderAt("/onboarding/summary", [
    http.patch("/api/config", async () => {
      await gate;
      return HttpResponse.json(
        { detail: "the platform is busy" },
        { status: 503 },
      );
    }),
    ...fake.handlers,
  ]);
  await screen.findByText(/This is what CoinPilot will do/);
  await user.click(start());
  expect(start()).toBeDisabled();
  release();
  expect(await screen.findByText("the platform is busy")).toBeInTheDocument();
  expect(start()).toBeEnabled();
  expect(router.state.location.pathname).toBe("/onboarding/summary");
});
