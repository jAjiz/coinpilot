import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
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

function proposal(): Proposal {
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
    ...initial,
  });
}

test("a live proposal is announced on Home", async () => {
  const user = userEvent.setup();
  renderAt("/", platform({ proposal: proposal() }).handlers);
  expect(
    await screen.findByRole("heading", { name: "Rebalance proposal" }),
  ).toBeInTheDocument();
  expect(screen.getByText("2 orders for €70.50")).toBeInTheDocument();
  expect(
    screen.getByText("Proposed Tuesday 20 October at 12:00"),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "Review" }));
  expect(
    await screen.findByRole("heading", { name: "Proposal" }),
  ).toBeInTheDocument();
});

test("without a proposal there is no card", async () => {
  renderAt("/", platform().handlers);
  await screen.findByText("Your account has not been read yet.");
  expect(
    screen.queryByRole("heading", { name: "Rebalance proposal" }),
  ).toBeNull();
});
