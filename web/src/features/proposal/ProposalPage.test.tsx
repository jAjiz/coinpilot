import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import type { Config, Proposal } from "@/api/queries";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

function leg(asset: string, side: string, amount: string, note: string | null) {
  return {
    asset,
    pair: `${asset}/EUR`,
    side,
    amount_fiat: amount,
    minimum_fiat: null,
    note,
  };
}

function proposal(extra: Partial<Proposal> = {}): Proposal {
  return {
    version: 3,
    status: "LIVE",
    trigger: "MANUAL",
    fiat: "EUR",
    updated_at: "2026-10-20T10:00:00Z",
    legs: [
      leg("BTC", "buy", "50", null),
      leg("ETH", "sell", "20.5", null),
      leg("SOL", "buy", "3", "below kraken's minimum"),
    ],
    ...extra,
  };
}

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: {
      fiat: "EUR",
      min_drift_pct: "2",
      onboarded_at: "2026-10-01T00:00:00Z",
    } as Config,
    proposal: proposal(),
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

test("every order is listed with its side, asset and amount", async () => {
  renderAt("/proposal", platform().handlers);
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
  expect(screen.getByText("Sell ETH for €20.50")).toBeInTheDocument();
  expect(screen.getByText("Total €70.50")).toBeInTheDocument();
  expect(
    screen.getByText("Proposed Tuesday 20 October at 12:00, on request"),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Orders" })).toBeInTheDocument();
});

test("a skipped leg is shown with its note", async () => {
  renderAt("/proposal", platform().handlers);
  expect(
    await screen.findByRole("heading", { name: "Skipped" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Buy SOL for €3.00: below kraken's minimum"),
  ).toBeInTheDocument();
});

test("when every leg is skipped nothing can be sent", async () => {
  const fake = platform({
    proposal: proposal({
      legs: [leg("SOL", "buy", "3", "below kraken's minimum")],
    }),
  });
  renderAt("/proposal", fake.handlers);
  expect(
    await screen.findByText(
      "Every order is below Kraken's minimum, so nothing can be sent.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/^Total/)).toBeNull();
});

test("a proposal from the schedule says so", async () => {
  renderAt(
    "/proposal",
    platform({ proposal: proposal({ trigger: "SCHEDULED" }) }).handlers,
  );
  expect(
    await screen.findByText(
      "Proposed Tuesday 20 October at 12:00, by your schedule",
    ),
  ).toBeInTheDocument();
});

test("without a proposal the page says so", async () => {
  const user = userEvent.setup();
  renderAt("/proposal", platform({ proposal: null }).handlers);
  expect(
    await screen.findByText("There is no proposal to review."),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "Back to Home" }));
  expect(await screen.findByRole("heading", { name: "Home" })).toBeVisible();
});

test("a failed load offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let fail = true;
  renderAt("/proposal", [
    http.get("/api/proposal", () =>
      fail
        ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
        : HttpResponse.json(proposal()),
    ),
    ...fake.handlers,
  ]);
  expect(await screen.findByText("platform down")).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
});

test("dismiss withdraws the proposal and goes Home", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/proposal", fake.handlers);
  await user.click(await screen.findByRole("button", { name: "Dismiss" }));
  expect(
    await screen.findByRole("heading", { name: "Home" }),
  ).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/");
  expect(fake.requests.map((r) => [r.method, r.path])).toEqual([
    ["DELETE", "/api/proposal"],
  ]);
  await screen.findByText("Your account has not been read yet.");
  expect(
    screen.queryByRole("heading", { name: "Rebalance proposal" }),
  ).toBeNull();
});

test("a proposal already gone is dismissed all the same", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/proposal", [
    http.delete("/api/proposal", () =>
      HttpResponse.json(
        { detail: "there is no live proposal" },
        { status: 404 },
      ),
    ),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/"));
});

test("dismissing says so while it runs and cannot be sent twice", async () => {
  const user = userEvent.setup();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fake = platform();
  renderAt("/proposal", [
    http.delete("/api/proposal", async () => {
      await gate;
      return new HttpResponse(null, { status: 204 });
    }),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Dismiss" }));
  expect(
    await screen.findByRole("button", { name: "Dismissing…" }),
  ).toBeDisabled();
  release();
  await screen.findByRole("heading", { name: "Home" });
});

test("another failure is shown and the proposal stays", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", [
    http.delete("/api/proposal", () =>
      HttpResponse.json({ detail: "platform down" }, { status: 500 }),
    ),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Dismiss" }));
  expect(await screen.findByText("platform down")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
});

test("dismiss is disabled while offline", async () => {
  renderAt("/proposal", platform().handlers);
  await screen.findByText("Buy BTC for €50.00");
  setOnline(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeDisabled(),
  );
});
