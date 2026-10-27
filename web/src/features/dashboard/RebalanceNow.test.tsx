import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import type { components } from "@/api/schema";
import type { Config, Proposal } from "@/api/queries";
import { createQueryClient } from "@/providers";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

type RebalanceOut = components["schemas"]["RebalanceOut"];

function leg(asset: string, side: string, amount: string) {
  return {
    asset,
    pair: `${asset}/EUR`,
    side,
    amount_fiat: amount,
    minimum_fiat: null,
    note: null,
  };
}

function proposal(): Proposal {
  return {
    version: 3,
    status: "LIVE",
    trigger: "MANUAL",
    fiat: "EUR",
    updated_at: "2026-10-20T10:00:00Z",
    legs: [leg("BTC", "buy", "50"), leg("ETH", "sell", "20.5")],
  };
}

function proposed(): RebalanceOut {
  return { status: "PROPOSED", legs: [], proposal: proposal(), messages: [] };
}

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

const openButton = () => screen.findByRole("button", { name: "Rebalance now" });

test("a rebalance found opens the proposal", async () => {
  const user = userEvent.setup();
  const fake = platform({ rebalanceResult: proposed() });
  renderAt("/", fake.handlers);
  await user.click(await openButton());
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Proposal" })).toBeInTheDocument();
  expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    "POST /api/rebalance",
  ]);
});

test("nothing to rebalance says why and stays on Home", async () => {
  const user = userEvent.setup();
  renderAt("/", platform().handlers);
  await user.click(await openButton());
  expect(await screen.findByText("Nothing to rebalance.")).toBeInTheDocument();
  expect(
    screen.getByText("the drift is below the threshold"),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument();
});

test("an evaluation that finds nothing removes the old card", async () => {
  const user = userEvent.setup();
  renderAt("/", platform({ proposal: proposal() }).handlers);
  expect(
    await screen.findByRole("heading", { name: "Rebalance proposal" }),
  ).toBeInTheDocument();
  await user.click(await openButton());
  expect(await screen.findByText("Nothing to rebalance.")).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "Rebalance proposal" }),
    ).toBeNull(),
  );
});

test("an operation already running is explained", async () => {
  const user = userEvent.setup();
  renderAt("/", [
    http.post("/api/rebalance", () =>
      HttpResponse.json(
        {
          detail:
            "an evaluation of this account is already running; try again shortly",
        },
        { status: 409 },
      ),
    ),
    ...platform().handlers,
  ]);
  await user.click(await openButton());
  expect(
    await screen.findByText(
      "An operation is already running; try again in a moment.",
    ),
  ).toBeInTheDocument();
  expect(await openButton()).toBeEnabled();
});

test("an unresolved order keeps the platform's words", async () => {
  const user = userEvent.setup();
  const detail =
    "an earlier order is still unresolved; try again in a few minutes";
  renderAt("/", [
    http.post("/api/rebalance", () =>
      HttpResponse.json({ detail }, { status: 409 }),
    ),
    ...platform().handlers,
  ]);
  await user.click(await openButton());
  expect(await screen.findByText(detail)).toBeInTheDocument();
});

test("rebalance now is disabled while it runs and while offline", async () => {
  const user = userEvent.setup();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  const fake = platform();
  renderAt("/", [
    http.post("/api/rebalance", async () => {
      calls += 1;
      await gate;
      return HttpResponse.json(fake.state.rebalanceResult);
    }),
    ...fake.handlers,
  ]);
  const button = await openButton();
  await user.click(button);
  const busy = await screen.findByRole("button", { name: "Checking…" });
  expect(busy).toBeDisabled();
  await user.click(busy);
  release();
  expect(await screen.findByText("Nothing to rebalance.")).toBeInTheDocument();
  expect(calls).toBe(1);

  setOnline(false);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Rebalance now" }),
    ).toBeDisabled(),
  );
});

// Every evaluation keeps a snapshot, so the portfolio is read again after it.
function countingPortfolio(fake: ReturnType<typeof platform>) {
  const counter = { reads: 0 };
  const handler = http.get("/api/portfolio", () => {
    counter.reads += 1;
    return fake.state.snapshot === null
      ? HttpResponse.json({ detail: "no snapshot yet" }, { status: 404 })
      : HttpResponse.json(fake.state.snapshot);
  });
  return { counter, handler };
}

test("nothing to rebalance reads the portfolio again", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const { counter, handler } = countingPortfolio(fake);
  renderAt("/", [handler, ...fake.handlers]);
  const button = await openButton();
  await waitFor(() => expect(counter.reads).toBe(1));
  await user.click(button);
  await screen.findByText("Nothing to rebalance.");
  await waitFor(() => expect(counter.reads).toBe(2));
});

test("a rebalance found reads the portfolio again", async () => {
  const user = userEvent.setup();
  const fake = platform({ rebalanceResult: proposed() });
  const { counter, handler } = countingPortfolio(fake);
  renderAt("/", [handler, ...fake.handlers]);
  const button = await openButton();
  await waitFor(() => expect(counter.reads).toBe(1));
  await user.click(button);
  await screen.findByText("Buy BTC for €50.00");
  await waitFor(() => expect(counter.reads).toBe(2));
});

test.each([
  ["nothing to rebalance", platform, "Nothing to rebalance."],
  [
    "a rebalance found",
    () => platform({ rebalanceResult: proposed() }),
    "Buy BTC for €50.00",
  ],
])("%s marks History to be read again", async (_, make, shown) => {
  const user = userEvent.setup();
  const client = createQueryClient();
  client.setQueryData(["sessions"], { pages: [[]], pageParams: [null] });
  renderAt("/", make().handlers, client);
  await user.click(await openButton());
  await screen.findByText(shown);
  await waitFor(() =>
    expect(client.getQueryState(["sessions"])?.isInvalidated).toBe(true),
  );
});
