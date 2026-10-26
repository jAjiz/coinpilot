import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import type { components } from "@/api/schema";
import type { Config } from "@/api/queries";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

type Leg = components["schemas"]["LegOut"];
type InvestOut = components["schemas"]["InvestOut"];

function leg(asset: string, amount: string, status: string, error = null) {
  return {
    asset,
    pair: `${asset}/EUR`,
    side: "buy",
    amount_fiat: amount,
    minimum_fiat: null,
    status,
    cl_ord_id: null,
    txid: null,
    cost: null,
    executed_volume: null,
    executed_price: null,
    fee: null,
    error,
    note: null,
    volume: null,
  } as Leg;
}

function out(status: string, legs: Leg[], preview: boolean): InvestOut {
  return { status, preview, legs, messages: [] };
}

const accepted = () => [
  leg("BTC", "60", "VALIDATED"),
  leg("ETH", "40", "VALIDATED"),
];

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: {
      fiat: "EUR",
      min_drift_pct: "2",
      onboarded_at: "2026-10-01T00:00:00Z",
    } as Config,
    ...initial,
  });
}

function setOnline(online: boolean) {
  Object.defineProperty(navigator, "onLine", {
    value: online,
    configurable: true,
  });
  act(() => {
    window.dispatchEvent(new Event(online ? "online" : "offline"));
  });
}

afterEach(() => setOnline(true));

const openButton = () => screen.findByRole("button", { name: "Invest now" });

test("invest now previews before it sends", async () => {
  const user = userEvent.setup();
  const fake = platform({ investPreview: out("PREVIEW", accepted(), true) });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  expect(await screen.findByText("Buy BTC for €60.00")).toBeInTheDocument();
  expect(screen.getByText("Buy ETH for €40.00")).toBeInTheDocument();
  expect(screen.getAllByText("Kraken accepts it")).toHaveLength(2);
  expect(screen.getByText("Total €100.00")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Prices move: the orders are computed again when you confirm.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Confirm: invest €100.00" }),
  ).toBeInTheDocument();
  expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    "POST /api/invest?preview=true",
  ]);
});

test("confirming sends, shows the outcome and refreshes the account", async () => {
  const user = userEvent.setup();
  const fake = platform({
    investPreview: out("PREVIEW", accepted(), true),
    investResult: out(
      "DONE",
      [leg("BTC", "60", "FILLED"), leg("ETH", "40", "FILLED")],
      false,
    ),
  });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  await user.click(
    await screen.findByRole("button", { name: "Confirm: invest €100.00" }),
  );
  expect(
    await screen.findByText("Every order was filled."),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Filled")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  await waitFor(() =>
    expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
      "POST /api/invest?preview=true",
      "POST /api/invest",
      "POST /api/portfolio/refresh",
    ]),
  );
});

test("a double tap on confirm sends once", async () => {
  const user = userEvent.setup();
  const fake = platform({
    investPreview: out("PREVIEW", accepted(), true),
    investResult: out("DONE", [leg("BTC", "60", "FILLED")], false),
  });
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let confirms = 0;
  renderAt("/", [
    http.post("/api/invest", async ({ request }) => {
      if (new URL(request.url).searchParams.get("preview") === "true") {
        return HttpResponse.json(fake.state.investPreview);
      }
      confirms += 1;
      await gate;
      return HttpResponse.json(fake.state.investResult);
    }),
    ...fake.handlers,
  ]);
  await user.click(await openButton());
  const confirm = await screen.findByRole("button", {
    name: "Confirm: invest €100.00",
  });
  await user.click(confirm);
  await user.click(confirm);
  release();
  expect(
    await screen.findByText("Every order was filled."),
  ).toBeInTheDocument();
  expect(confirms).toBe(1);
});

test("a rejected leg is not counted, and with none accepted there is no confirm", async () => {
  const user = userEvent.setup();
  const fake = platform({
    investPreview: out(
      "PREVIEW",
      [
        leg("BTC", "60", "VALIDATED"),
        leg("ETH", "40", "REJECTED", "bad" as never),
      ],
      true,
    ),
  });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  expect(await screen.findByText("Total €60.00")).toBeInTheDocument();
  expect(screen.getByText("Kraken refuses it: bad")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Confirm: invest €60.00" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  fake.state.investPreview = out(
    "PREVIEW",
    [leg("BTC", "60", "REJECTED"), leg("ETH", "40", "SKIPPED")],
    true,
  );
  await user.click(await openButton());
  expect(
    await screen.findByText("Kraken would accept none of these orders."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(await openButton()).toBeInTheDocument();
});

test("nothing to invest says why", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  expect(await screen.findByText("Nothing to invest.")).toBeInTheDocument();
  expect(
    screen.getByText("there is no free cash to invest"),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(await openButton()).toBeInTheDocument();
});

test("cancel sends nothing", async () => {
  const user = userEvent.setup();
  const fake = platform({ investPreview: out("PREVIEW", accepted(), true) });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  await user.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(await openButton()).toBeInTheDocument();
  expect(fake.requests.map((r) => r.path)).toEqual([
    "/api/invest?preview=true",
  ]);
});

test("an operation already running is explained", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/", [
    http.post("/api/invest", () =>
      HttpResponse.json(
        {
          detail:
            "an evaluation of this account is already running; try again shortly",
        },
        { status: 409 },
      ),
    ),
    ...fake.handlers,
  ]);
  await user.click(await openButton());
  expect(
    await screen.findByText(
      "An operation is already running; try again in a moment.",
    ),
  ).toBeInTheDocument();
  expect(await openButton()).toBeEnabled();
});

test("an unreachable Kraken is explained", async () => {
  const user = userEvent.setup();
  const fake = platform({ investPreview: out("PREVIEW", accepted(), true) });
  renderAt("/", [
    http.post("/api/invest", ({ request }) =>
      new URL(request.url).searchParams.get("preview") === "true"
        ? HttpResponse.json(fake.state.investPreview)
        : HttpResponse.json(
            { detail: "kraken could not be read; nothing was sent" },
            { status: 503 },
          ),
    ),
    ...fake.handlers,
  ]);
  await user.click(await openButton());
  await user.click(
    await screen.findByRole("button", { name: "Confirm: invest €100.00" }),
  );
  expect(
    await screen.findByText("Kraken didn't answer; nothing was changed."),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "Confirm: invest €100.00" }),
  ).toBeEnabled();
});

test("an outcome that sent nothing does not refresh", async () => {
  const user = userEvent.setup();
  const fake = platform({
    investPreview: out("PREVIEW", accepted(), true),
    investResult: out(
      "ERROR",
      [leg("BTC", "60", "FAILED", "boom" as never)],
      false,
    ),
  });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  await user.click(
    await screen.findByRole("button", { name: "Confirm: invest €100.00" }),
  );
  expect(
    await screen.findByText("The operation failed. Nothing more was sent."),
  ).toBeInTheDocument();
  expect(screen.getByText("Failed: boom")).toBeInTheDocument();
  expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    "POST /api/invest?preview=true",
    "POST /api/invest",
  ]);
});

test("invest now is disabled while offline", async () => {
  const fake = platform();
  renderAt("/", fake.handlers);
  await openButton();
  setOnline(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Invest now" })).toBeDisabled(),
  );
});
