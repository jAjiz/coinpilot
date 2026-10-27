import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { createQueryClient } from "@/providers";
import { renderAt } from "@/test/render";

const me = { id: "u1", email: "a@b.c", provider: "google", status: "active" };
const onboardedConfig = {
  fiat: "EUR",
  onboarded_at: "2026-01-01T00:00:00Z",
  // Settings tells the automation, so the stored fields must be there.
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
};

const signedIn = http.get("/api/auth/me", () => HttpResponse.json(me));
const signedOut = [
  http.get("/api/auth/me", () =>
    HttpResponse.json({ detail: "not signed in" }, { status: 401 }),
  ),
  http.post("/api/auth/refresh", () =>
    HttpResponse.json({ detail: "refresh refused" }, { status: 401 }),
  ),
];
const onboarded = http.get("/api/config", () =>
  HttpResponse.json(onboardedConfig),
);
// Home reads the account and the proposal; neither exists here.
const noAccount = [
  http.get("/api/portfolio", () =>
    HttpResponse.json({ detail: "no snapshot" }, { status: 404 }),
  ),
  http.get("/api/proposal", () =>
    HttpResponse.json({ detail: "no proposal" }, { status: 404 }),
  ),
];
const noKey = [
  http.get("/api/config", () =>
    HttpResponse.json({ detail: "no settings" }, { status: 404 }),
  ),
  http.get("/api/credentials/status", () =>
    HttpResponse.json({ registered: false }),
  ),
  http.get("/api/assets", () =>
    HttpResponse.json({ assets: [], cash_target_pct: "100" }),
  ),
];

test("a signed-out user is sent to /login", async () => {
  const router = renderAt("/settings", signedOut);
  await screen.findByRole("heading", { name: "CoinPilot" });
  expect(router.state.location.pathname).toBe("/login");
});

test("a user without a key starts onboarding at the key", async () => {
  const router = renderAt("/", [signedIn, ...noKey]);
  await screen.findByRole("heading", { name: "Kraken key" });
  expect(router.state.location.pathname).toBe("/onboarding/key");
});

test("a deep link cannot skip a step", async () => {
  const router = renderAt("/onboarding/summary", [signedIn, ...noKey]);
  await screen.findByRole("heading", { name: "Kraken key" });
  expect(router.state.location.pathname).toBe("/onboarding/key");
});

test("an onboarded user cannot re-enter onboarding", async () => {
  const router = renderAt("/onboarding/key", [
    signedIn,
    onboarded,
    ...noAccount,
  ]);
  await screen.findByRole("heading", { name: "Home" });
  expect(router.state.location.pathname).toBe("/");
});

test("an onboarded user reaches the page asked for", async () => {
  renderAt("/settings", [signedIn, onboarded]);
  await screen.findByRole("heading", { name: "Settings" });
  expect(screen.getByText("Signed in as a@b.c.")).toBeInTheDocument();
});

test("a platform that is down is not a sign-out", async () => {
  let calls = 0;
  const router = renderAt("/settings", [
    http.get("/api/auth/me", () => {
      calls += 1;
      return calls === 1
        ? HttpResponse.json({ detail: "platform down" }, { status: 503 })
        : HttpResponse.json(me);
    }),
    onboarded,
  ]);
  await screen.findByText("platform down");
  expect(router.state.location.pathname).toBe("/settings");
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("heading", { name: "Settings" });
  expect(router.state.location.pathname).toBe("/settings");
});

test("the login page shows the refusal", async () => {
  renderAt("/login?error=this%20account%20is%20disabled", signedOut);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "this account is disabled",
  );
});

test("the sign-in link leaves the application", async () => {
  renderAt("/login", signedOut);
  const link = await screen.findByRole("link", { name: "Sign in with Google" });
  expect(link.getAttribute("href")).toBe("/api/auth/login/google");
});

test("a signed-in user opening the login page goes home", async () => {
  const router = renderAt("/login", [signedIn, onboarded, ...noAccount]);
  await screen.findByRole("heading", { name: "Home" });
  expect(router.state.location.pathname).toBe("/");
});

test("an unknown path goes home", async () => {
  const router = renderAt("/nowhere", [signedIn, onboarded, ...noAccount]);
  await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  await screen.findByRole("heading", { name: "Home" });
});

test("a failed background refetch keeps the page", async () => {
  let calls = 0;
  const client = createQueryClient();
  renderAt(
    "/settings",
    [
      http.get("/api/auth/me", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json(me)
          : HttpResponse.json({ detail: "platform down" }, { status: 503 });
      }),
      onboarded,
      http.get("/api/assets", () =>
        HttpResponse.json({ assets: [], cash_target_pct: "100" }),
      ),
      http.get("/api/credentials/status", () =>
        HttpResponse.json({ registered: false }),
      ),
    ],
    client,
  );
  await screen.findByRole("heading", { name: "Settings" });
  await client.invalidateQueries({ queryKey: ["me"] });
  await waitFor(() => expect(calls).toBe(2));
  expect(client.getQueryState(["me"])?.status).toBe("error");
  expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});

test.each(["/api/config", "/api/credentials/status"])(
  "a first load where %s is down offers to try again",
  async (path) => {
    renderAt("/", [
      http.get(path, () =>
        HttpResponse.json({ detail: "platform down" }, { status: 503 }),
      ),
      signedIn,
      http.get("/api/config", () =>
        HttpResponse.json({ detail: "no settings" }, { status: 404 }),
      ),
      http.get("/api/credentials/status", () =>
        HttpResponse.json({ registered: false }),
      ),
      http.get("/api/assets", () =>
        HttpResponse.json({ assets: [], cash_target_pct: "100" }),
      ),
    ]);
    await screen.findByText("platform down");
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  },
);
