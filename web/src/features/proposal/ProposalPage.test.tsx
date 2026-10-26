import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import { proposalKey, type Config, type Proposal } from "@/api/queries";
import { createQueryClient } from "@/providers";
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

function sent(
  asset: string,
  side: string,
  amount: string,
  status: string,
  error: string | null = null,
) {
  return {
    ...leg(asset, side, amount, null),
    status,
    cl_ord_id: null,
    txid: null,
    cost: null,
    executed_volume: null,
    executed_price: null,
    fee: null,
    error,
    volume: null,
  };
}

const approveButton = () => screen.findByRole("button", { name: "Approve" });

test("approving asks first, then sends the version on screen", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  expect(
    await screen.findByText("Send 2 orders for €70.50?"),
  ).toBeInTheDocument();
  expect(fake.requests).toEqual([]);
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  await screen.findByText("Every order was filled.");
  expect(fake.requests[0]).toEqual({
    method: "POST",
    path: "/api/proposal/approve",
    body: { version: 3 },
  });
});

test("an approval shows what was sent and refreshes the account", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("Every order was filled."),
  ).toBeInTheDocument();
  expect(screen.getByText("Buy BTC for €50.00")).toBeInTheDocument();
  expect(screen.getByText("Sell ETH for €20.50")).toBeInTheDocument();
  expect(screen.getAllByText("Filled")).toHaveLength(2);
  await waitFor(() =>
    expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
      "POST /api/proposal/approve",
      "POST /api/portfolio/refresh",
    ]),
  );
  // The outcome stays although the proposal query now reads nothing.
  expect(screen.getByText("Every order was filled.")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "Back to Home" }));
  expect(
    await screen.findByRole("heading", { name: "Home" }),
  ).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/");
  await screen.findByRole("button", { name: "Invest now" });
  expect(
    screen.queryByRole("heading", { name: "Rebalance proposal" }),
  ).toBeNull();
});

test("a double tap on confirm sends once", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let approvals = 0;
  renderAt("/proposal", [
    http.post("/api/proposal/approve", async () => {
      approvals += 1;
      await gate;
      return HttpResponse.json({
        status: "DONE",
        legs: [sent("BTC", "buy", "50", "FILLED")],
        proposal: null,
        messages: [],
      });
    }),
    ...fake.handlers,
  ]);
  await user.click(await approveButton());
  const confirm = await screen.findByRole("button", { name: "Confirm" });
  await user.click(confirm);
  await user.click(confirm);
  expect(
    await screen.findByRole("button", { name: "Sending…" }),
  ).toBeDisabled();
  release();
  expect(
    await screen.findByText("Every order was filled."),
  ).toBeInTheDocument();
  expect(approvals).toBe(1);
});

test("a new version is shown for a new review", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  await screen.findByText("Send 2 orders for €70.50?");
  fake.state.proposal = proposal({
    version: 4,
    legs: [leg("ADA", "buy", "15", null)],
  });
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("The proposal changed; review it again."),
  ).toBeInTheDocument();
  expect(screen.getByText("Buy ADA for €15.00")).toBeInTheDocument();
  expect(screen.queryByText("Buy BTC for €50.00")).toBeNull();
  expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  await user.click(await approveButton());
  expect(
    screen.queryByText("The proposal changed; review it again."),
  ).toBeNull();
  expect(screen.getByText("Send 1 order for €15.00?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  await screen.findByText("Every order was filled.");
  expect(fake.requests.map((r) => [r.path, r.body])).toEqual([
    ["/api/proposal/approve", { version: 3 }],
    ["/api/proposal/approve", { version: 4 }],
    ["/api/portfolio/refresh", null],
  ]);
});

test("a proposal withdrawn under the user ends on the empty page with the notice", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", [
    http.post("/api/proposal/approve", () =>
      HttpResponse.json(
        {
          detail: "the plan changed",
          proposal: null,
          messages: ["the drift is below the threshold"],
        },
        { status: 409 },
      ),
    ),
    ...fake.handlers,
  ]);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("There is no proposal to review."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("The proposal changed; review it again."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("the drift is below the threshold"),
  ).toBeInTheDocument();
});

test("a proposal already gone ends on the empty page", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  await screen.findByRole("button", { name: "Confirm" });
  fake.state.proposal = null;
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("There is no proposal to review."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a partial approval says so", async () => {
  const user = userEvent.setup();
  const fake = platform({
    approveResult: {
      status: "PARTIAL",
      legs: [
        sent("BTC", "buy", "50", "FILLED"),
        sent("ETH", "sell", "20.5", "FAILED", "EOrder:Insufficient funds"),
      ],
      proposal: null,
      messages: [],
    },
  });
  renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText(
      "Kraken refused some orders; the others were filled.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Failed: EOrder:Insufficient funds"),
  ).toBeInTheDocument();
});

test("another approval failure is shown and the confirmation stays", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", [
    http.post("/api/proposal/approve", () =>
      HttpResponse.json(
        { detail: "kraken could not be read; nothing was sent" },
        { status: 503 },
      ),
    ),
    ...fake.handlers,
  ]);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("Kraken didn't answer; nothing was changed."),
  ).toBeInTheDocument();
  expect(screen.getByText("Send 2 orders for €70.50?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
});

test("a failed refresh after an approval is said", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", [
    http.post("/api/portfolio/refresh", () =>
      HttpResponse.json({ detail: "down" }, { status: 503 }),
    ),
    ...fake.handlers,
  ]);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(
    await screen.findByText("Every order was filled."),
  ).toBeInTheDocument();
  expect(
    await screen.findByText(
      "The new balances could not be read. Kraken didn't answer; nothing was changed.",
    ),
  ).toBeInTheDocument();
});

test("cancel sends nothing", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/proposal", fake.handlers);
  await user.click(await approveButton());
  await user.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(await approveButton()).toBeInTheDocument();
  expect(screen.queryByText("Send 2 orders for €70.50?")).toBeNull();
  expect(fake.requests).toEqual([]);
});

test("approve is disabled while offline", async () => {
  const user = userEvent.setup();
  renderAt("/proposal", platform().handlers);
  await user.click(await approveButton());
  setOnline(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled(),
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
});

test("without orders there is nothing to approve", async () => {
  renderAt(
    "/proposal",
    platform({
      proposal: proposal({
        legs: [leg("SOL", "buy", "3", "below kraken's minimum")],
      }),
    }).handlers,
  );
  await screen.findByRole("button", { name: "Dismiss" });
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
});

test("dismiss is disabled while the confirmation is open", async () => {
  const user = userEvent.setup();
  renderAt("/proposal", platform().handlers);
  await user.click(await approveButton());
  await screen.findByRole("button", { name: "Confirm" });
  expect(screen.getByRole("button", { name: "Dismiss" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
});

test("approve cannot be tapped while a dismissal is in flight", async () => {
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
  await screen.findByRole("button", { name: "Dismissing…" });
  const approve = screen.getByRole("button", { name: "Approve" });
  expect(approve).toBeDisabled();
  await user.click(approve);
  expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  release();
  await screen.findByRole("heading", { name: "Home" });
  expect(fake.requests.map((r) => r.path)).not.toContain(
    "/api/proposal/approve",
  );
});

test("a new version read under an open confirmation closes it", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const client = createQueryClient();
  renderAt("/proposal", fake.handlers, client);
  await user.click(await approveButton());
  await screen.findByText("Send 2 orders for €70.50?");
  fake.state.proposal = proposal({
    version: 4,
    legs: [leg("ADA", "buy", "15", null)],
  });
  await act(() => client.invalidateQueries({ queryKey: proposalKey }));
  expect(
    await screen.findByText("The proposal changed; review it again."),
  ).toBeInTheDocument();
  expect(screen.getByText("Buy ADA for €15.00")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  await user.click(await approveButton());
  expect(screen.getByText("Send 1 order for €15.00?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  await screen.findByText("Every order was filled.");
  expect(fake.requests[0]).toEqual({
    method: "POST",
    path: "/api/proposal/approve",
    body: { version: 4 },
  });
});

test("a proposal withdrawn under an open confirmation closes it", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const client = createQueryClient();
  renderAt("/proposal", fake.handlers, client);
  await user.click(await approveButton());
  await screen.findByText("Send 2 orders for €70.50?");
  fake.state.proposal = null;
  await act(() => client.invalidateQueries({ queryKey: proposalKey }));
  expect(
    await screen.findByText("There is no proposal to review."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("The proposal changed; review it again."),
  ).toBeInTheDocument();
});
