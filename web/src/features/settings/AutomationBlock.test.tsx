import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { fakePlatform } from "@/test/fakePlatform";
import { createQueryClient } from "@/providers";
import { renderAt } from "@/test/render";
import { server } from "@/test/server";

const CONFIG: Config = {
  fiat: "EUR",
  invest_cash_enabled: true,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "1",
  min_order_fiat: "0",
  invest_cadence_mode: "INTERVAL",
  invest_interval_days: 7,
  invest_interval_months: null,
  invest_cadence_anchor: "2026-10-26T11:00:00Z",
  rebalance_cadence_mode: "INTERVAL",
  rebalance_interval_days: null,
  rebalance_interval_months: 3,
  rebalance_cadence_anchor: "2026-10-01T11:00:00Z",
  next_invest_at: null,
  next_rebalance_at: null,
  onboarded_at: "2026-10-01T00:00:00Z",
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-27T08:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

function platform() {
  return fakePlatform({
    registered: true,
    config: CONFIG,
    nextInvestAt: "2026-11-02T11:00:00Z",
    nextRebalanceAt: "2027-01-01T11:00:00Z",
  });
}

function pickDate(label: string, value: string) {
  const input = screen.getByLabelText(label);
  const set = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  set.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

test("the summary tells the automation and the next runs", async () => {
  renderAt("/settings", platform().handlers);
  expect(
    await screen.findByText("Next invest: Monday 2 November at 12:00"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Next rebalance: Friday 1 January at 12:00"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Edit automation" }),
  ).toBeInTheDocument();
});

test("changing a cadence moves the next run", async () => {
  const user = userEvent.setup();
  renderAt("/settings", platform().handlers);
  await user.click(
    await screen.findByRole("button", { name: "Edit automation" }),
  );
  await user.selectOptions(screen.getByLabelText("Invest cadence"), "monthly");
  pickDate("Invest start date", "2026-11-01");
  await user.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(
    await screen.findByText("Next invest: Sunday 1 November at 12:00"),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Invest cadence")).not.toBeInTheDocument();
});

test("cancel sends nothing", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/settings", fake.handlers);
  await user.click(
    await screen.findByRole("button", { name: "Edit automation" }),
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByLabelText("Invest cadence")).not.toBeInTheDocument();
  expect(fake.requests).toEqual([]);
});

test("a failed refetch keeps the open form and its edits", async () => {
  const user = userEvent.setup();
  const client = createQueryClient();
  renderAt("/settings", platform().handlers, client);
  await user.click(
    await screen.findByRole("button", { name: "Edit automation" }),
  );
  await user.selectOptions(screen.getByLabelText("Invest cadence"), "daily");
  server.use(
    http.get("/api/config", () =>
      HttpResponse.json({ detail: "platform down" }, { status: 503 }),
    ),
  );
  await client.invalidateQueries({ queryKey: ["config"] });
  await waitFor(() =>
    expect(client.getQueryState(["config"])?.status).toBe("error"),
  );
  expect(screen.getByLabelText("Invest cadence")).toHaveValue("daily");
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});

const CUSTOM: Config = {
  ...CONFIG,
  invest_interval_days: 10,
  invest_cadence_anchor: "2026-10-26T11:00:00Z",
  // Noon in Madrid, so only the invest cadence is custom.
  rebalance_cadence_anchor: "2026-10-01T10:00:00Z",
};

async function openCustom(fake: ReturnType<typeof platform>) {
  const user = userEvent.setup();
  renderAt("/settings", fake.handlers);
  await user.click(
    await screen.findByRole("button", { name: "Edit automation" }),
  );
  expect(screen.getByLabelText("Invest cadence")).toHaveValue("custom");
  return user;
}

function customPlatform() {
  return fakePlatform({
    registered: true,
    config: CUSTOM,
    nextInvestAt: "2026-11-02T11:00:00Z",
    nextRebalanceAt: "2027-01-01T11:00:00Z",
  });
}

test("a custom cadence's fields are edited and sent", async () => {
  const fake = customPlatform();
  const user = await openCustom(fake);
  expect(screen.getByLabelText("Days")).toHaveValue("10");
  expect(screen.getByLabelText("Starts")).toHaveValue("2026-10-26T12:00");
  const days = screen.getByLabelText("Days");
  await user.clear(days);
  await user.type(days, "14");
  await user.click(screen.getByRole("button", { name: "Save and continue" }));
  await waitFor(() => expect(fake.requests).toHaveLength(1));
  expect(fake.requests[0].body).toMatchObject({
    invest_cadence_mode: "INTERVAL",
    invest_interval_days: 14,
    invest_interval_months: null,
    invest_cadence_anchor: "2026-10-26T11:00:00Z",
  });
});

test("an untouched custom cadence is not sent", async () => {
  const fake = customPlatform();
  const user = await openCustom(fake);
  await user.click(screen.getByRole("button", { name: "Save and continue" }));
  await waitFor(() => expect(fake.requests).toHaveLength(1));
  expect(Object.keys(fake.requests[0].body as object)).not.toContain(
    "invest_interval_days",
  );
});

test("an interval of nothing is refused before sending", async () => {
  const fake = customPlatform();
  const user = await openCustom(fake);
  const days = screen.getByLabelText("Days");
  await user.clear(days);
  await user.type(days, "0");
  await user.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(
    await screen.findByText("Choose at least one day or one month."),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([]);
});

test("a day count that is not whole is refused next to its field", async () => {
  const fake = customPlatform();
  const user = await openCustom(fake);
  const days = screen.getByLabelText("Days");
  await user.clear(days);
  await user.type(days, "1.5");
  await user.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(
    await screen.findByText("Enter whole days from 0 to 3650."),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([]);
});
