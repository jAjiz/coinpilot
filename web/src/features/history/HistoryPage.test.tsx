import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { createQueryClient } from "@/providers";
import type { components } from "@/api/schema";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

type Session = components["schemas"]["EvaluationOut"];
type Order = components["schemas"]["OrderOut"];

function session(n: number, extra: Partial<Session> = {}): Session {
  const day = String(n).padStart(2, "0");
  return {
    id: `00000000-0000-4000-8000-0000000000${day}`,
    started_at: `2026-10-${day}T09:00:00Z`,
    finished_at: `2026-10-${day}T09:00:05Z`,
    duration_ms: 5000,
    status: "DONE",
    operation: "INVEST",
    trigger: "SCHEDULER",
    log_messages: null,
    ...extra,
  };
}

const ORDER: Order = {
  cl_ord_id: "c1",
  session_id: session(5).id,
  txid: "T1",
  pair: "BTC/EUR",
  asset: "BTC",
  side: "buy",
  reason: "invest",
  status: "FILLED",
  requested_fiat: "50",
  executed_volume: "0.001",
  executed_price: "49900",
  fee: "0.13",
  cost: "50",
  error: null,
  created_at: "2026-10-05T09:00:01Z",
};

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: {
      fiat: "EUR",
      onboarded_at: "2026-10-01T00:00:00Z",
    } as Config,
    ...initial,
  });
}

test("there is no way to show runs that did nothing", async () => {
  const fake = platform({
    sessions: [session(5), session(6, { status: "NOTHING_TO_DO" })],
  });
  renderAt("/history", fake.handlers);
  expect(await screen.findByText("Invest · scheduled")).toBeInTheDocument();
  expect(screen.queryByText("Nothing to do")).toBeNull();
  expect(screen.queryByRole("button", { name: /nothing to do/i })).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("switch")).toBeNull();
});

test("a run expands into its messages and its orders", async () => {
  const user = userEvent.setup();
  const fake = platform({
    sessions: [session(5, { log_messages: "bought BTC\n\nall done" })],
    orders: [ORDER],
  });
  renderAt("/history", fake.handlers);
  await user.click(await screen.findByRole("button", { name: /Invest/ }));
  expect(await screen.findByText("bought BTC")).toBeInTheDocument();
  expect(screen.getByText("all done")).toBeInTheDocument();
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
  expect(screen.getByText("Filled")).toBeInTheDocument();
  expect(screen.getByText("Cost €50.00 · fee €0.13")).toBeInTheDocument();
});

test("a run without orders says so", async () => {
  const user = userEvent.setup();
  renderAt("/history", platform({ sessions: [session(5)] }).handlers);
  await user.click(await screen.findByRole("button", { name: /Invest/ }));
  expect(
    await screen.findByText("No orders are linked to this run."),
  ).toBeInTheDocument();
});

test("orders are read only when a run expands", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)], orders: [ORDER] });
  const gets: string[] = [];
  renderAt("/history", [
    http.get("/api/orders", ({ request }) => {
      gets.push(request.url);
    }),
    ...fake.handlers,
  ]);
  const row = await screen.findByRole("button", { name: /Invest/ });
  expect(gets).toEqual([]);
  await user.click(row);
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
  expect(gets).toHaveLength(1);
  expect(new URL(gets[0]).searchParams.get("session")).toBe(session(5).id);
});

test("load more continues after the last run", async () => {
  const user = userEvent.setup();
  const all = Array.from({ length: 25 }, (_, i) => session(i + 1));
  const fake = platform({ sessions: all });
  const gets: string[] = [];
  renderAt("/history", [
    http.get("/api/sessions", ({ request }) => {
      gets.push(request.url);
    }),
    ...fake.handlers,
  ]);
  await screen.findAllByRole("button", { name: /Invest/ });
  expect(screen.getAllByRole("button", { name: /Invest/ })).toHaveLength(20);
  await user.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findAllByRole("button", { name: /Invest/ });
  await vi.waitFor(() =>
    expect(screen.getAllByRole("button", { name: /Invest/ })).toHaveLength(25),
  );
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  expect(gets).toHaveLength(2);
  // newest first: the 20th row is session 6
  expect(new URL(gets[1]).searchParams.get("before")).toBe(session(6).id);
});

test("no runs says why", async () => {
  renderAt("/history", platform().handlers);
  expect(
    await screen.findByText(
      "Nothing has happened yet. Runs that invest, rebalance or fail show here.",
    ),
  ).toBeInTheDocument();
});

test("a failed read offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)] });
  let fail = true;
  renderAt("/history", [
    http.get("/api/sessions", () =>
      fail
        ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
        : undefined,
    ),
    ...fake.handlers,
  ]);
  expect(await screen.findByText("platform down")).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Invest · scheduled")).toBeInTheDocument();
});

test("a failed orders read offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)], orders: [ORDER] });
  let fail = true;
  renderAt("/history", [
    http.get("/api/orders", () =>
      fail
        ? HttpResponse.json({ detail: "orders down" }, { status: 500 })
        : undefined,
    ),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: /Invest/ }));
  expect(await screen.findByText("orders down")).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
});

// The guard reads /api/config once under its own key; the page's useConfig
// makes the second request, which is the one these tests hold back.
test("a failed config read offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)] });
  let calls = 0;
  let fail = true;
  renderAt("/history", [
    http.get("/api/config", () =>
      ++calls > 1 && fail
        ? HttpResponse.json({ detail: "config down" }, { status: 500 })
        : undefined,
    ),
    ...fake.handlers,
  ]);
  expect(await screen.findByText("config down")).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Invest · scheduled")).toBeInTheDocument();
});

test("a slow config shows the orders skeleton, not a crash", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)], orders: [ORDER] });
  let calls = 0;
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  renderAt("/history", [
    http.get("/api/config", async () => {
      if (++calls > 1) await gate;
    }),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: /Invest/ }));
  expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
  expect(screen.queryByText("Buy BTC for €50.00")).toBeNull();
  release();
  expect(await screen.findByText("Buy BTC for €50.00")).toBeInTheDocument();
});

test("a failed load more keeps the runs and offers a retry", async () => {
  const user = userEvent.setup();
  const all = Array.from({ length: 25 }, (_, i) => session(i + 1));
  const fake = platform({ sessions: all });
  let fail = true;
  renderAt("/history", [
    http.get("/api/sessions", ({ request }) =>
      fail && new URL(request.url).searchParams.has("before")
        ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
        : undefined,
    ),
    ...fake.handlers,
  ]);
  await screen.findAllByRole("button", { name: /Invest/ });
  await user.click(screen.getByRole("button", { name: "Load more" }));

  expect(await screen.findByText("platform down")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /Invest/ })).toHaveLength(20);
  expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await vi.waitFor(() =>
    expect(screen.getAllByRole("button", { name: /Invest/ })).toHaveLength(25),
  );
  expect(screen.queryByText("platform down")).toBeNull();
});

test("a failed background read keeps the runs on screen", async () => {
  const user = userEvent.setup();
  const fake = platform({ sessions: [session(5)] });
  const client = createQueryClient();
  let fail = false;
  renderAt(
    "/history",
    [
      http.get("/api/sessions", () =>
        fail
          ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
          : undefined,
      ),
      ...fake.handlers,
    ],
    client,
  );
  await screen.findByText("Invest · scheduled");
  fail = true;
  await act(() => client.refetchQueries({ queryKey: ["sessions"] }));

  expect(await screen.findByText("platform down")).toBeInTheDocument();
  expect(screen.getByText("Invest · scheduled")).toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await vi.waitFor(() =>
    expect(screen.queryByText("platform down")).toBeNull(),
  );
  expect(screen.getByText("Invest · scheduled")).toBeInTheDocument();
});
