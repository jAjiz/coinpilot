import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import type { Config } from "@/api/queries";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

const CONFIG = { fiat: "EUR" } as Config;

function holding(
  asset: string,
  value: string | null,
  extra: Partial<FakeState["portfolio"]["holdings"][number]> = {},
) {
  return {
    asset,
    amount: "1",
    price: value === null ? null : "1",
    value,
    managed: false,
    locked: false,
    target_pct: null,
    weight_pct: null,
    ...extra,
  };
}

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: CONFIG,
    portfolio: {
      cash: "100",
      holdings: [holding("BTC", "300"), holding("ETH", "600")],
    },
    ...initial,
  });
}

function rowOf(asset: string) {
  return screen.getByRole("listitem", { name: asset });
}

test("the currency is chosen first, with its warning", async () => {
  const user = userEvent.setup();
  const fake = platform({ config: null, assets: [] });
  renderAt("/onboarding/portfolio", fake.handlers);
  expect(
    await screen.findByText(/It cannot be changed later\./),
  ).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Currency"), "EUR");
  await user.click(screen.getByRole("button", { name: "Save currency" }));
  await screen.findByLabelText("Target for BTC");
  expect(screen.getByText("Currency: EUR")).toBeInTheDocument();
  expect(fake.requests.map((r) => [r.method, r.path, r.body])).toEqual([
    ["PATCH", "/api/config", { fiat: "EUR" }],
    ["POST", "/api/portfolio/refresh", null],
  ]);
});

test("holdings are prefilled with today's weights", async () => {
  renderAt("/onboarding/portfolio", platform().handlers);
  expect(await screen.findByLabelText("Target for BTC")).toHaveValue("30");
  expect(screen.getByLabelText("Target for ETH")).toHaveValue("60");
  expect(screen.getByText("Cash (EUR) target: 10 %")).toBeInTheDocument();
  expect(within(rowOf("BTC")).getByText("€300.00")).toBeInTheDocument();
  expect(within(rowOf("BTC")).getByText("30 % of the account")).toBeVisible();
  expect(screen.getByRole("switch", { name: "Manage BTC" })).toBeChecked();
});

test("the cash target follows every keystroke", async () => {
  const user = userEvent.setup();
  renderAt("/onboarding/portfolio", platform().handlers);
  const btc = await screen.findByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "10");
  expect(screen.getByText("Cash (EUR) target: 30 %")).toBeInTheDocument();
});

test("locked and unpriced balances cannot be managed", async () => {
  renderAt(
    "/onboarding/portfolio",
    platform({
      portfolio: {
        cash: "100",
        holdings: [
          holding("BTC", "300"),
          holding("DOGE", null),
          holding("DOT", "50", { locked: true }),
        ],
      },
    }).handlers,
  );
  await screen.findByLabelText("Target for BTC");
  expect(
    screen.getByText("Kraken has no DOGE/EUR price, so it cannot be managed."),
  ).toBeInTheDocument();
  expect(
    within(rowOf("DOT")).getByText(
      "Locked (staked or reserved), so it cannot be managed.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Manage DOGE")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Manage DOT")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Target for DOT")).not.toBeInTheDocument();
});

test("saving writes one PUT per managed asset and moves on", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/onboarding/portfolio", fake.handlers);
  await screen.findByLabelText("Target for BTC");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await screen.findByRole("heading", { name: "Automation" });
  expect(router.state.location.pathname).toBe("/onboarding/automation");
  expect(
    fake.requests
      .filter((r) => r.path.startsWith("/api/assets"))
      .map((r) => [r.method, r.path, r.body]),
  ).toEqual([
    ["PUT", "/api/assets/BTC", { target_pct: "30" }],
    ["PUT", "/api/assets/ETH", { target_pct: "60" }],
  ]);
});

test("Save targets stays disabled while the step advances", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let advancing = false;
  let held = 0;
  renderAt("/onboarding/portfolio", [
    http.get("/api/config", async () => {
      if (advancing) {
        held += 1;
        await gate;
      }
      return undefined;
    }),
    ...fake.handlers,
  ]);
  await screen.findByLabelText("Target for BTC");
  const saveButton = () => screen.getByRole("button", { name: "Save targets" });
  advancing = true;
  await user.click(saveButton());
  await waitFor(() => expect(held).toBeGreaterThan(0));
  expect(saveButton()).toBeDisabled();
  await user.click(saveButton());
  release();
  await screen.findByRole("heading", { name: "Automation" });
  expect(fake.requests.filter((r) => r.method === "PUT")).toHaveLength(2);
});

test("an account with nothing held says so", async () => {
  renderAt(
    "/onboarding/portfolio",
    platform({ portfolio: { cash: "100", holdings: [] } }).handlers,
  );
  expect(
    await screen.findByText(
      "Nothing is held yet; add the assets you want to buy.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Asset to add")).toBeInTheDocument();
});

test("a comma is a decimal separator", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/onboarding/portfolio", fake.handlers);
  const btc = await screen.findByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "12,5");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await screen.findByRole("heading", { name: "Automation" });
  expect(fake.requests).toContainEqual({
    method: "PUT",
    path: "/api/assets/BTC",
    body: { target_pct: "12.5" },
  });
});

test("an invalid target is refused next to its row, before anything is sent", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/onboarding/portfolio", fake.handlers);
  const btc = await screen.findByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "1.234");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await within(rowOf("BTC")).findByRole("alert")).toHaveTextContent(
    "Enter a percentage from 0 to 100, with up to two decimals.",
  );
  expect(fake.requests.filter((r) => r.method === "PUT")).toEqual([]);
});

test("targets above 100 are refused before anything is sent", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/onboarding/portfolio", fake.handlers);
  const btc = await screen.findByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "50");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The targets add up to more than 100 %.",
  );
  expect(fake.requests.filter((r) => r.method === "PUT")).toEqual([]);
});

test("managing nothing is refused", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/onboarding/portfolio", fake.handlers);
  await screen.findByLabelText("Target for BTC");
  await user.click(screen.getByRole("switch", { name: "Manage BTC" }));
  await user.click(screen.getByRole("switch", { name: "Manage ETH" }));
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Manage at least one asset.",
  );
  expect(fake.requests.filter((r) => r.method === "PUT")).toEqual([]);
});

test("an added asset is upper-cased, and a repeated one is refused", async () => {
  const user = userEvent.setup();
  renderAt("/onboarding/portfolio", platform().handlers);
  await screen.findByLabelText("Target for BTC");
  await user.type(screen.getByLabelText("Asset to add"), "sol");
  await user.click(screen.getByRole("button", { name: "Add" }));
  expect(await screen.findByLabelText("Target for SOL")).toHaveValue("");
  expect(screen.getByLabelText("Asset to add")).toHaveValue("");
  await user.type(screen.getByLabelText("Asset to add"), "btc");
  await user.click(screen.getByRole("button", { name: "Add" }));
  expect(screen.getByText("BTC is already in the list.")).toBeInTheDocument();
});

test("an added asset Kraken cannot trade shows the reason in its row", async () => {
  const user = userEvent.setup();
  const fake = platform({ untradable: ["XYZ"] });
  renderAt("/onboarding/portfolio", fake.handlers);
  await screen.findByLabelText("Target for BTC");
  await user.type(screen.getByLabelText("Asset to add"), "xyz");
  await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(await screen.findByLabelText("Target for XYZ"), "5");
  const btc = screen.getByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "20");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await within(rowOf("XYZ")).findByRole("alert")).toHaveTextContent(
    "kraken has no tradable XYZ/EUR pair",
  );
  expect(within(rowOf("BTC")).queryByRole("alert")).not.toBeInTheDocument();
});

test("an alias of a listed asset is refused when the platform names it", async () => {
  const user = userEvent.setup();
  const fake = platform({ aliases: { XXBT: "BTC" } });
  const router = renderAt("/onboarding/portfolio", fake.handlers);
  await screen.findByLabelText("Target for BTC");
  await user.type(screen.getByLabelText("Asset to add"), "xxbt");
  await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(await screen.findByLabelText("Target for XXBT"), "5");
  const btc = screen.getByLabelText("Target for BTC");
  await user.clear(btc);
  await user.type(btc, "20");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await within(rowOf("XXBT")).findByRole("alert")).toHaveTextContent(
    "Kraken calls XXBT BTC, which is already in the list.",
  );
  expect(router.state.location.pathname).toBe("/onboarding/portfolio");
});

test("coming back keeps stored targets and deletes an asset switched off", async () => {
  const user = userEvent.setup();
  const fake = platform({
    assets: [{ asset: "BTC", pair: "BTC/EUR", target_pct: "50" }],
  });
  renderAt("/onboarding/portfolio", fake.handlers);
  expect(await screen.findByLabelText("Target for BTC")).toHaveValue("50");
  expect(screen.getByLabelText("Target for ETH")).toHaveValue("60");
  await user.click(screen.getByRole("switch", { name: "Manage BTC" }));
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await screen.findByRole("heading", { name: "Automation" });
  expect(
    fake.requests
      .filter((r) => r.path.startsWith("/api/assets"))
      .map((r) => [r.method, r.path]),
  ).toEqual([
    ["DELETE", "/api/assets/BTC"],
    ["PUT", "/api/assets/ETH"],
  ]);
});

test("a managed asset Kraken no longer prices has its target removed", async () => {
  const user = userEvent.setup();
  const fake = platform({
    portfolio: {
      cash: "100",
      holdings: [
        holding("BTC", "300", { managed: true, target_pct: "50" }),
        holding("SOL", null, { managed: true, target_pct: "20" }),
      ],
    },
    assets: [
      { asset: "BTC", pair: "BTC/EUR", target_pct: "50" },
      { asset: "SOL", pair: "SOL/EUR", target_pct: "20" },
    ],
  });
  renderAt("/onboarding/portfolio", fake.handlers);
  await screen.findByLabelText("Target for BTC");
  expect(
    within(rowOf("SOL")).getByText(
      "Kraken has no SOL/EUR price, so it cannot be managed. Its 20 % target is removed when you save.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Target for SOL")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await screen.findByRole("heading", { name: "Automation" });
  expect(
    fake.requests
      .filter((r) => r.path.startsWith("/api/assets"))
      .map((r) => [r.method, r.path]),
  ).toEqual([["DELETE", "/api/assets/SOL"]]);
});

test("moving weight between two assets never passes 100 on the way", async () => {
  const user = userEvent.setup();
  const fake = platform({
    portfolio: {
      cash: "0",
      holdings: [holding("BTC", "60"), holding("ETH", "40")],
    },
    assets: [
      { asset: "BTC", pair: "BTC/EUR", target_pct: "60" },
      { asset: "ETH", pair: "ETH/EUR", target_pct: "40" },
    ],
  });
  renderAt("/onboarding/portfolio", fake.handlers);
  const btc = await screen.findByLabelText("Target for BTC");
  const eth = screen.getByLabelText("Target for ETH");
  await user.clear(btc);
  await user.type(btc, "40");
  await user.clear(eth);
  await user.type(eth, "60");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await screen.findByRole("heading", { name: "Automation" });
  expect(
    fake.requests
      .filter((r) => r.method === "PUT")
      .map((r) => [r.path, r.body]),
  ).toEqual([
    ["/api/assets/BTC", { target_pct: "40" }],
    ["/api/assets/ETH", { target_pct: "60" }],
  ]);
});

test("an unreachable Kraken on the read offers a retry", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let calls = 0;
  renderAt("/onboarding/portfolio", [
    http.post("/api/portfolio/refresh", () => {
      calls += 1;
      return calls === 1
        ? HttpResponse.json(
            { detail: "kraken did not return balance; nothing was recorded" },
            { status: 503 },
          )
        : undefined;
    }),
    ...fake.handlers,
  ]);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Kraken didn't answer; nothing was changed.",
  );
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByLabelText("Target for BTC");
  await waitFor(() => expect(calls).toBe(2));
});

test("sending again after a failed write does not repeat the earlier deletes", async () => {
  const user = userEvent.setup();
  const fake = platform({
    assets: [
      { asset: "BTC", pair: "BTC/EUR", target_pct: "50" },
      { asset: "ETH", pair: "ETH/EUR", target_pct: "10" },
    ],
    untradable: ["ETH"],
  });
  renderAt("/onboarding/portfolio", fake.handlers);
  const eth = await screen.findByLabelText("Target for ETH");
  await user.click(screen.getByRole("switch", { name: "Manage BTC" }));
  await user.clear(eth);
  await user.type(eth, "20");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await within(rowOf("ETH")).findByRole("alert");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save targets" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await waitFor(() =>
    expect(fake.requests.filter((r) => r.method === "PUT")).toHaveLength(2),
  );
  expect(fake.requests.filter((r) => r.method === "DELETE")).toHaveLength(1);
});

test("the rows stay when reading the stored assets back fails", async () => {
  const user = userEvent.setup();
  const fake = platform({
    assets: [{ asset: "ETH", pair: "ETH/EUR", target_pct: "10" }],
    untradable: ["ETH"],
  });
  let reads = 0;
  renderAt("/onboarding/portfolio", [
    http.get("/api/assets", () => {
      reads += 1;
      return reads <= 2
        ? undefined
        : HttpResponse.json({ detail: "down" }, { status: 503 });
    }),
    ...fake.handlers,
  ]);
  const eth = await screen.findByLabelText("Target for ETH");
  await user.clear(eth);
  await user.type(eth, "20");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  await within(rowOf("ETH")).findByRole("alert");
  await waitFor(() => expect(reads).toBeGreaterThan(1));
  expect(screen.getByLabelText("Target for ETH")).toBeInTheDocument();
  expect(within(rowOf("ETH")).getByRole("alert")).toHaveTextContent(
    "kraken has no tradable ETH/EUR pair",
  );
});

test("a failed delete of an asset with no row is shown on the form", async () => {
  const user = userEvent.setup();
  const fake = platform({
    assets: [{ asset: "OLD", pair: "OLD/EUR", target_pct: "5" }],
  });
  renderAt("/onboarding/portfolio", [
    // the refresh does not list OLD, so it has no row
    http.post("/api/portfolio/refresh", () =>
      HttpResponse.json({
        as_of: "2026-10-20T10:00:00Z",
        fiat: "EUR",
        total_value: "400",
        cash: "100",
        cash_target_pct: "95",
        cash_weight_pct: null,
        holdings: [holding("BTC", "300")],
      }),
    ),
    http.delete("/api/assets/OLD", () =>
      HttpResponse.json({ detail: "cannot delete OLD" }, { status: 500 }),
    ),
    ...fake.handlers,
  ]);
  await screen.findByLabelText("Target for BTC");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "cannot delete OLD",
  );
});
