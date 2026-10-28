import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import type { Config, Portfolio } from "@/api/queries";
import { createQueryClient } from "@/providers";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

type Holding = Portfolio["holdings"][number];

function config(minDrift = "2"): Config {
  return {
    fiat: "EUR",
    min_drift_pct: minDrift,
    onboarded_at: "2026-10-01T00:00:00Z",
  } as Config;
}

function held(asset: string, extra: Partial<Holding> = {}): Holding {
  return {
    asset,
    amount: "1",
    price: "1",
    value: "100",
    managed: true,
    locked: false,
    target_pct: null,
    weight_pct: null,
    ...extra,
  };
}

function snapshot(extra: Partial<Portfolio> = {}): Portfolio {
  return {
    as_of: "2026-10-20T10:00:00Z",
    fiat: "EUR",
    total_value: "1000",
    cash: "100",
    cash_target_pct: "10",
    cash_weight_pct: "10",
    holdings: [
      held("BTC", { value: "325", weight_pct: "32.5", target_pct: "30" }),
      held("ETH", { value: "575", weight_pct: "57.5", target_pct: "60" }),
      held("XRP", { value: "50", managed: false }),
    ],
    ...extra,
  };
}

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: config(),
    snapshot: snapshot(),
    ...initial,
  });
}

function rowOf(name: string) {
  return screen.getByRole("listitem", { name });
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

afterEach(() => {
  setOnline(true);
  Object.defineProperty(document, "visibilityState", {
    value: "visible",
    configurable: true,
  });
});

test("the account's value, split into managed and unmanaged", async () => {
  renderAt("/", platform().handlers);
  expect(await screen.findByText("€1,050.00")).toBeInTheDocument();
  expect(screen.getByText("Account value")).toBeInTheDocument();
  expect(
    screen.getByText("Managed €1,000.00 · unmanaged €50.00"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Read Tuesday 20 October at 12:00"),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Locked balances/)).not.toBeInTheDocument();
});

test("locked balances are said to be unvalued", async () => {
  const fake = platform({
    snapshot: snapshot({
      holdings: [
        ...snapshot().holdings,
        held("DOT", { value: null, price: null, managed: false, locked: true }),
      ],
    }),
  });
  renderAt("/", fake.handlers);
  expect(
    await screen.findByText(
      "Locked balances (staked or reserved) are not valued.",
    ),
  ).toBeInTheDocument();
});

test("each managed asset and cash have a row with weight, target and drift", async () => {
  renderAt("/", platform().handlers);
  await screen.findByRole("heading", { name: "Allocation" });
  const btc = within(await screen.findByRole("listitem", { name: "BTC" }));
  expect(btc.getByText("32.5 % · target 30 %")).toBeInTheDocument();
  expect(btc.getByText("+2.5 pts")).toBeInTheDocument();
  const eth = within(rowOf("ETH"));
  expect(eth.getByText("57.5 % · target 60 %")).toBeInTheDocument();
  expect(eth.getByText("-2.5 pts")).toBeInTheDocument();
  const cash = within(rowOf("Cash"));
  expect(cash.getByText("10 % · target 10 %")).toBeInTheDocument();
  expect(screen.queryByRole("listitem", { name: "XRP" })).toBeNull();
});

test("each row shows the amount held and its market value", async () => {
  renderAt(
    "/",
    platform({
      snapshot: snapshot({
        holdings: [
          held("BTC", {
            amount: "0.01230000",
            value: "325",
            weight_pct: "32.5",
            target_pct: "30",
          }),
          held("DOT", { amount: "4", value: null, price: null }),
        ],
      }),
    }).handlers,
  );
  const btc = within(await screen.findByRole("listitem", { name: "BTC" }));
  expect(btc.getByText("0.0123 BTC · €325.00")).toBeInTheDocument();
  expect(within(rowOf("DOT")).getByText("4 DOT")).toBeInTheDocument();
  expect(within(rowOf("Cash")).getByText("€100.00")).toBeInTheDocument();
});

test("rows drifted past the threshold are highlighted", async () => {
  renderAt("/", platform().handlers);
  await screen.findByRole("listitem", { name: "BTC" });
  expect(rowOf("BTC")).toHaveAttribute("data-drifted", "true");
  expect(rowOf("ETH")).toHaveAttribute("data-drifted", "true");
  expect(rowOf("Cash")).not.toHaveAttribute("data-drifted");
});

test("with a higher threshold nothing is highlighted", async () => {
  renderAt("/", platform({ config: config("3") }).handlers);
  await screen.findByRole("listitem", { name: "BTC" });
  expect(rowOf("BTC")).not.toHaveAttribute("data-drifted");
  expect(rowOf("ETH")).not.toHaveAttribute("data-drifted");
});

test("the bar's fill is the weight and its mark the target", async () => {
  renderAt("/", platform().handlers);
  await screen.findByRole("listitem", { name: "BTC" });
  const row = rowOf("BTC");
  expect(row.querySelector('[data-slot="fill"]')).toHaveStyle({
    width: "32.5%",
  });
  expect(row.querySelector('[data-slot="mark"]')).toHaveStyle({ left: "30%" });
});

test("an asset with no price and a snapshot without cash percentages still render", async () => {
  const fake = platform({
    snapshot: snapshot({
      cash_weight_pct: null,
      holdings: [
        held("BTC", { value: null, price: null, target_pct: "30" }),
        held("ETH", { value: "575", weight_pct: "57.5", target_pct: "60" }),
      ],
    }),
  });
  renderAt("/", fake.handlers);
  await screen.findByRole("listitem", { name: "BTC" });
  const btc = within(rowOf("BTC"));
  expect(btc.getByText("No price in EUR")).toBeInTheDocument();
  expect(rowOf("BTC").querySelector('[data-slot="fill"]')).toBeNull();
  const cash = within(rowOf("Cash"));
  expect(cash.getByText("Not recorded in this reading")).toBeInTheDocument();
  expect(rowOf("Cash").querySelector('[data-slot="fill"]')).toBeNull();
  expect(within(rowOf("ETH")).getByText("-2.5 pts")).toBeInTheDocument();
});

test("an account never read offers a refresh", async () => {
  const user = userEvent.setup();
  const fake = platform({
    snapshot: null,
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
    portfolio: { cash: "700", holdings: [held("BTC", { value: "300" })] },
  });
  renderAt("/", fake.handlers);
  expect(
    await screen.findByText("Your account has not been read yet."),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("€1,000.00")).toBeInTheDocument();
  expect(fake.requests.map((r) => [r.method, r.path])).toEqual([
    ["POST", "/api/portfolio/refresh"],
  ]);
});

test("refresh reads Kraken and shows the new reading", async () => {
  const user = userEvent.setup();
  const fake = platform({
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
    portfolio: { cash: "700", holdings: [held("BTC", { value: "300" })] },
  });
  renderAt("/", fake.handlers);
  await screen.findByText("€1,050.00");
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("€1,000.00")).toBeInTheDocument();
  expect(screen.queryByText("€1,050.00")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
});

function refreshes(fake: { requests: { method: string; path: string }[] }) {
  return fake.requests.filter(
    (r) => r.method === "POST" && r.path === "/api/portfolio/refresh",
  ).length;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

test("opening Home reads Kraken once per load", async () => {
  const fake = platform({
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
    portfolio: { cash: "700", holdings: [held("BTC", { value: "300" })] },
  });
  const router = renderAt("/", fake.handlers, createQueryClient(), {
    readOnOpen: true,
  });
  expect(await screen.findByText("€1,000.00")).toBeInTheDocument();
  expect(refreshes(fake)).toBe(1);
  await act(() => router.navigate("/history"));
  await act(() => router.navigate("/"));
  await screen.findByText("€1,000.00");
  expect(refreshes(fake)).toBe(1);
});

test("coming back to the foreground keeps a recent reading", async () => {
  const fake = platform({
    snapshot: snapshot({ as_of: new Date().toISOString() }),
  });
  renderAt("/", fake.handlers);
  await screen.findByText("€1,050.00");
  setVisibility("hidden");
  setVisibility("visible");
  expect(refreshes(fake)).toBe(0);
});

test("coming back to the foreground reads a stale reading again", async () => {
  const fake = platform({
    snapshot: snapshot({
      as_of: new Date(Date.now() - 6 * 60_000).toISOString(),
    }),
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
    portfolio: { cash: "700", holdings: [held("BTC", { value: "300" })] },
  });
  renderAt("/", fake.handlers);
  await screen.findByText("€1,050.00");
  setVisibility("hidden");
  setVisibility("visible");
  expect(await screen.findByText("€1,000.00")).toBeInTheDocument();
  expect(refreshes(fake)).toBe(1);
});

test("refreshing says Kraken is being read", async () => {
  const user = userEvent.setup();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fake = platform();
  renderAt("/", [
    http.post("/api/portfolio/refresh", async () => {
      await gate;
      return HttpResponse.json(snapshot());
    }),
    ...fake.handlers,
  ]);
  await screen.findByText("€1,050.00");
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(
    await screen.findByRole("button", { name: "Reading Kraken…" }),
  ).toBeDisabled();
  release();
  await screen.findByRole("button", { name: "Refresh" });
});

test("an unreachable Kraken on refresh keeps the last reading", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/", [
    http.post("/api/portfolio/refresh", () =>
      HttpResponse.json(
        { detail: "kraken did not return the balances; nothing was recorded" },
        { status: 503 },
      ),
    ),
    ...fake.handlers,
  ]);
  await screen.findByText("€1,050.00");
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(
    await screen.findByText("Kraken didn't answer; nothing was changed."),
  ).toBeInTheDocument();
  expect(screen.getByText("€1,050.00")).toBeInTheDocument();
});

test("a failed load offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let fail = true;
  renderAt("/", [
    http.get("/api/portfolio", () =>
      fail
        ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
        : HttpResponse.json(snapshot()),
    ),
    ...fake.handlers,
  ]);
  expect(await screen.findByText("platform down")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Allocation" })).toBeNull();
  fail = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("€1,050.00")).toBeInTheDocument();
});

test("refresh is disabled while offline", async () => {
  renderAt("/", platform().handlers);
  await screen.findByText("€1,050.00");
  setOnline(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled(),
  );
});

test("a failed background refetch keeps the value on screen", async () => {
  const client = createQueryClient();
  const fake = platform();
  let fail = false;
  renderAt(
    "/",
    [
      http.get("/api/portfolio", () =>
        fail
          ? HttpResponse.json({ detail: "platform down" }, { status: 500 })
          : HttpResponse.json(snapshot()),
      ),
      ...fake.handlers,
    ],
    client,
  );
  await screen.findByText("€1,050.00");
  fail = true;
  await client.invalidateQueries({ queryKey: ["portfolio"] });
  await waitFor(() =>
    expect(client.getQueryState(["portfolio"])?.status).toBe("error"),
  );
  expect(screen.getByText("€1,050.00")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Allocation" })).toBeVisible();
});
