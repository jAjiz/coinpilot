import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

const CONFIG: Config = {
  fiat: "EUR",
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
  next_rebalance_at: null,
  onboarded_at: null,
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-19T08:00:00Z"));
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
    ...initial,
  });
}

async function open(fake = platform()) {
  const router = renderAt("/onboarding/automation", fake.handlers);
  await screen.findByLabelText("Invest cadence");
  return router;
}

const save = () => screen.getByRole("button", { name: "Save and continue" });

// userEvent cannot type into a date input; this is what a picker does.
function pickDate(label: string, value: string) {
  const input = screen.getByLabelText(label);
  const set = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  set.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

test("a new configuration starts from the wizard's defaults", async () => {
  await open();
  expect(screen.getByLabelText("Invest cadence")).toHaveValue("monthly");
  expect(screen.getByLabelText("Rebalance cadence")).toHaveValue("quarterly");
  expect(screen.getByLabelText("Invest start date")).toHaveValue("2026-10-19");
  expect(screen.getByLabelText("Rebalance start date")).toHaveValue(
    "2026-10-19",
  );
  for (const name of [
    "Invest free cash automatically",
    "When investing, buy the most underweight assets first",
    "Rebalance automatically, without asking",
  ]) {
    expect(screen.getByRole("switch", { name })).not.toBeChecked();
  }
  expect(
    screen.getByLabelText("Rebalance only when an asset drifts more than"),
  ).toHaveValue("1");
  expect(screen.getByLabelText("Skip orders smaller than")).toHaveValue("0");
  expect(
    screen.getByText(
      "At each invest run, free EUR is invested toward your targets. Off, you invest it yourself from Home.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Runs on the 19th of each month."),
  ).toBeInTheDocument();
});

test("the default date is the local day", async () => {
  vi.setSystemTime(new Date("2026-10-19T22:30:00Z"));
  await open();
  expect(screen.getByLabelText("Invest start date")).toHaveValue("2026-10-20");
  expect(screen.getByLabelText("Rebalance start date")).toHaveValue(
    "2026-10-20",
  );
});

test("as soon as possible hides the start date", async () => {
  const user = userEvent.setup();
  await open();
  await user.selectOptions(
    screen.getByLabelText("Invest cadence"),
    "As soon as possible (every 15 min)",
  );
  expect(screen.queryByLabelText("Invest start date")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Rebalance start date")).toBeInTheDocument();
});

test("the weekday and the day of the month are told", async () => {
  const user = userEvent.setup();
  await open();
  await user.selectOptions(screen.getByLabelText("Invest cadence"), "Weekly");
  expect(screen.getByText("Runs every Monday.")).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Invest cadence"), "Monthly");
  pickDate("Invest start date", "2026-01-31");
  expect(
    await screen.findByText(
      "Runs on the 31st of each month; in a shorter month, on its last day.",
    ),
  ).toBeInTheDocument();
});

test("saving sends one PATCH and opens the summary", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = await open(fake);
  await user.selectOptions(screen.getByLabelText("Invest cadence"), "Weekly");
  await user.click(save());
  await waitFor(() =>
    expect(router.state.location.pathname).toBe("/onboarding/summary"),
  );
  expect(fake.requests).toEqual([
    {
      method: "PATCH",
      path: "/api/config",
      body: {
        invest_cadence_mode: "INTERVAL",
        invest_interval_days: 7,
        invest_interval_months: null,
        invest_cadence_anchor: "2026-10-19T10:00:00.000Z",
        rebalance_cadence_mode: "INTERVAL",
        rebalance_interval_days: null,
        rebalance_interval_months: 3,
        rebalance_cadence_anchor: "2026-10-19T10:00:00.000Z",
        invest_cash_enabled: false,
        cash_rebalance_enabled: false,
        auto_rebalance_enabled: false,
        min_drift_pct: "1",
        min_order_fiat: "0",
      },
    },
  ]);
});

test("a saved configuration is shown when coming back", async () => {
  await open(
    platform({
      invest_cadence_mode: "INTERVAL",
      invest_interval_days: 7,
      invest_cadence_anchor: "2026-11-02T11:00:00.000Z",
      rebalance_cadence_mode: "INTERVAL",
      rebalance_interval_months: 6,
      rebalance_cadence_anchor: "2026-11-03T11:00:00.000Z",
      invest_cash_enabled: true,
      auto_rebalance_enabled: true,
      min_drift_pct: "2.5",
      min_order_fiat: "10",
    }),
  );
  expect(screen.getByLabelText("Invest cadence")).toHaveValue("weekly");
  expect(screen.getByLabelText("Invest start date")).toHaveValue("2026-11-02");
  expect(screen.getByLabelText("Rebalance cadence")).toHaveValue("half-yearly");
  expect(screen.getByLabelText("Rebalance start date")).toHaveValue(
    "2026-11-03",
  );
  expect(
    screen.getByRole("switch", { name: "Invest free cash automatically" }),
  ).toBeChecked();
  expect(
    screen.getByRole("switch", {
      name: "When investing, buy the most underweight assets first",
    }),
  ).not.toBeChecked();
  expect(
    screen.getByRole("switch", {
      name: "Rebalance automatically, without asking",
    }),
  ).toBeChecked();
  expect(
    screen.getByLabelText("Rebalance only when an asset drifts more than"),
  ).toHaveValue("2.5");
  expect(screen.getByLabelText("Skip orders smaller than")).toHaveValue("10");
});

test("a custom cadence is kept unless changed", async () => {
  const user = userEvent.setup();
  const fake = platform({
    invest_cadence_mode: "INTERVAL",
    invest_interval_days: 2,
    invest_cadence_anchor: "2026-11-02T11:00:00.000Z",
    rebalance_cadence_mode: "INTERVAL",
    rebalance_interval_months: 3,
    rebalance_cadence_anchor: "2026-11-02T11:00:00.000Z",
  });
  await open(fake);
  expect(screen.getByLabelText("Invest cadence")).toHaveValue("custom");
  expect(
    screen.getByText(
      "Set through the API; kept unless you choose another option.",
    ),
  ).toBeInTheDocument();
  await user.click(save());
  await waitFor(() => expect(fake.requests).toHaveLength(1));
  const body = fake.requests[0].body as Record<string, unknown>;
  expect(Object.keys(body).filter((key) => key.startsWith("invest_c"))).toEqual(
    ["invest_cash_enabled"],
  );
  expect(Object.keys(body)).not.toContain("invest_interval_days");
  expect(body.rebalance_cadence_mode).toBe("INTERVAL");
});

test("an invalid threshold is refused next to its field", async () => {
  const user = userEvent.setup();
  const fake = platform();
  await open(fake);
  const drift = screen.getByLabelText(
    "Rebalance only when an asset drifts more than",
  );
  await user.clear(drift);
  await user.type(drift, "1.25");
  await user.click(save());
  expect(
    await screen.findByText(
      "Enter a percentage from 0 to 100, with up to one decimal.",
    ),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([]);

  await user.clear(drift);
  await user.type(drift, "1,5");
  const minimum = screen.getByLabelText("Skip orders smaller than");
  await user.clear(minimum);
  await user.type(minimum, "x");
  await user.click(save());
  expect(
    await screen.findByText(
      "Enter an amount of 0 or more, with up to one decimal.",
    ),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([]);
});

test("an empty start date is refused next to its field", async () => {
  const user = userEvent.setup();
  const fake = platform();
  await open(fake);
  pickDate("Rebalance start date", "");
  await user.click(save());
  expect(await screen.findByText("Choose a start date.")).toBeInTheDocument();
  expect(fake.requests).toEqual([]);
});

test("the platform's refusal is shown", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/onboarding/automation", [
    http.patch("/api/config", () =>
      HttpResponse.json(
        { detail: "the cadence is too short" },
        { status: 422 },
      ),
    ),
    ...fake.handlers,
  ]);
  await screen.findByLabelText("Invest cadence");
  await user.click(save());
  expect(
    await screen.findByText("the cadence is too short"),
  ).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/onboarding/automation");
  expect(save()).toBeEnabled();
});
