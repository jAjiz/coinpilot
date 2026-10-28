import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { approveKey, investKey, refreshAfter } from "@/api/operations";
import { createQueryClient } from "@/providers";
import { fakePlatform, type FakeState } from "@/test/fakePlatform";
import { renderAt } from "@/test/render";

afterEach(() => {
  vi.restoreAllMocks();
});

function platform(initial: Partial<FakeState> = {}) {
  return fakePlatform({
    registered: true,
    config: {
      fiat: "EUR",
      paused: false,
      onboarded_at: "2026-10-01T00:00:00Z",
    } as Config,
    ...initial,
  });
}

test("each edit opens in its own window and Cancel closes it", async () => {
  const user = userEvent.setup();
  renderAt("/settings", platform().handlers);
  for (const name of ["Edit targets", "Edit automation"]) {
    await user.click(await screen.findByRole("button", { name }));
    const dialog = await screen.findByRole("dialog", { name });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  }
  await user.click(screen.getByRole("button", { name: "Replace key" }));
  const dialog = await screen.findByRole("dialog", { name: "Replace key" });
  await user.click(within(dialog).getByRole("button", { name: "Close" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});

test("the key is replaced only by one Kraken accepts", async () => {
  const user = userEvent.setup();
  const fake = platform({
    keyReply: {
      status: 422,
      body: { detail: { rejection: "invalid_key" } },
    },
  });
  renderAt("/settings", fake.handlers);
  await screen.findByText(/A key is saved, verified on 20 October 2026/);
  await user.click(screen.getByRole("button", { name: "Replace key" }));
  await user.type(screen.getByLabelText("API key"), "new-key");
  await user.type(screen.getByLabelText("Private key"), "new-secret");
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Kraken did not accept this key.",
  );
  expect(fake.state.registered).toBe(true);
  expect(screen.getByText(/A key is saved/)).toBeInTheDocument();
});

test("an accepted replacement shows the accepted view of onboarding", async () => {
  const user = userEvent.setup();
  renderAt("/settings", platform().handlers);
  await user.click(await screen.findByRole("button", { name: "Replace key" }));
  await user.type(screen.getByLabelText("API key"), "k");
  await user.type(screen.getByLabelText("Private key"), "s");
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText("Key saved.");
  expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Replace key" }),
  ).toBeInTheDocument();
});

test("deleting the key takes a second tap", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/settings", fake.handlers);
  await user.click(await screen.findByRole("button", { name: "Delete key" }));
  expect(fake.requests).toEqual([]);
  expect(
    screen.getByText(
      "Without a key, CoinPilot stops investing and rebalancing until you save a new one.",
    ),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Confirm: delete key" }));
  await screen.findByText(
    "No key is saved. CoinPilot cannot trade until you save one.",
  );
  expect(fake.requests).toEqual([
    { method: "DELETE", path: "/api/credentials", body: null },
  ]);
  expect(screen.getByLabelText("API key")).toBeInTheDocument();
});

test("with no key, the form is open", async () => {
  renderAt("/settings", platform({ registered: false }).handlers);
  await screen.findByText(
    "No key is saved. CoinPilot cannot trade until you save one.",
  );
  expect(screen.getByLabelText("Private key")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete key" }),
  ).not.toBeInTheDocument();
});

test("pause is saved and shown on Home", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const router = renderAt("/settings", fake.handlers);
  await user.click(
    await screen.findByRole("switch", { name: "Pause everything" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: "Pause everything" }),
    ).toBeChecked(),
  );
  expect(fake.requests).toEqual([
    { method: "PATCH", path: "/api/config", body: { paused: true } },
  ]);
  expect(
    screen.getByText(
      "While paused, nothing runs on schedule. Invest now and Rebalance now still work. On resume, the next runs are scheduled from then: nothing missed while paused runs.",
    ),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "Home" }));
  await screen.findByText(/Automation is paused\./);
  await user.click(screen.getByRole("link", { name: "Resume in Settings" }));
  expect(router.state.location.pathname).toBe("/settings");
});

test("Home says nothing when automation runs", async () => {
  renderAt("/", platform().handlers);
  await screen.findByRole("heading", { name: "Home" });
  expect(screen.queryByText(/Automation is paused/)).not.toBeInTheDocument();
});

test("sign out forgets everything", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const client = createQueryClient();
  const router = renderAt("/settings", fake.handlers, client);
  await screen.findByText("Signed in as a@b.c.");
  // a held outcome of this user, as an invest or an approval leaves it
  for (const key of [investKey, approveKey]) {
    client.getMutationCache().build(client, {
      mutationKey: key,
      mutationFn: () => Promise.resolve("first user"),
    });
  }
  expect(client.getMutationCache().getAll()).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByRole("link", { name: "Sign in with Google" });
  expect(router.state.location.pathname).toBe("/login");
  expect(fake.requests).toEqual([
    { method: "POST", path: "/api/auth/logout", body: null },
  ]);
  // only the login page's own read of who is signed in: and it found nobody
  const kept = client.getQueryCache().getAll();
  expect(kept.map((q) => q.queryKey)).toEqual([["me"]]);
  expect(kept[0].state.data).toBeNull();
  expect(client.getMutationCache().getAll()).toEqual([]);
});

test("a failed sign out stays on Settings", async () => {
  const user = userEvent.setup();
  const client = createQueryClient();
  const router = renderAt(
    "/settings",
    [
      http.post("/api/auth/logout", () =>
        HttpResponse.json({ detail: "logout failed" }, { status: 500 }),
      ),
      ...platform().handlers,
    ],
    client,
  );
  await screen.findByText("Signed in as a@b.c.");
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("logout failed");
  expect(router.state.location.pathname).toBe("/settings");
  expect(client.getQueryCache().getAll().length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
});

test("every sending button is disabled while offline", async () => {
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
  renderAt("/settings", platform().handlers);
  await screen.findByText(/A key is saved/);
  for (const name of ["Delete key", "Sign out"]) {
    expect(screen.getByRole("button", { name })).toBeDisabled();
  }
  expect(
    screen.getByRole("switch", { name: "Pause everything" }),
  ).toHaveAttribute("data-disabled");
});

test("a button is disabled while its request is in flight", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  renderAt("/settings", [
    http.post("/api/auth/logout", async () => {
      await gate;
      return HttpResponse.json({ detail: "slow" }, { status: 500 });
    }),
    ...platform().handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDisabled(),
  );
  release();
  await screen.findByText("slow");
});

test("a failed delete spends its confirmation", async () => {
  const user = userEvent.setup();
  const fake = platform();
  let fail = true;
  const router = renderAt("/settings", [
    http.delete("/api/credentials", () =>
      fail
        ? HttpResponse.json({ detail: "kraken is down" }, { status: 500 })
        : new HttpResponse(null, { status: 204 }),
    ),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Delete key" }));
  await user.click(screen.getByRole("button", { name: "Confirm: delete key" }));
  await screen.findByText("kraken is down");
  expect(
    screen.queryByRole("button", { name: "Confirm: delete key" }),
  ).not.toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/settings");
  fail = false;
  // a second tap is needed again
  await user.click(screen.getByRole("button", { name: "Delete key" }));
  expect(
    screen.getByRole("button", { name: "Confirm: delete key" }),
  ).toBeInTheDocument();
});

test("a key saved after a lost delete is not one tap from deletion", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/settings", [
    http.delete("/api/credentials", () => {
      fake.state.registered = false;
      return HttpResponse.json(
        { detail: "no key is registered" },
        { status: 404 },
      );
    }),
    ...fake.handlers,
  ]);
  await user.click(await screen.findByRole("button", { name: "Delete key" }));
  await user.click(screen.getByRole("button", { name: "Confirm: delete key" }));
  await screen.findByText(/No key is saved/);
  await user.type(screen.getByLabelText("API key"), "k");
  await user.type(screen.getByLabelText("Private key"), "s");
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText(/A key is saved/);
  expect(
    screen.queryByRole("button", { name: "Confirm: delete key" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Delete key" }),
  ).toBeInTheDocument();
});

test("a request still in flight at sign out leaves nothing of the first user", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const proposal = {
    version: 3,
    legs: [],
  } as unknown as NonNullable<FakeState["proposal"]>;
  const fake = platform({
    rebalanceResult: {
      status: "PROPOSED",
      legs: [],
      proposal,
      messages: [],
    },
  });
  const client = createQueryClient();
  const router = renderAt(
    "/",
    [
      http.post("/api/rebalance", async () => {
        await gate;
        return HttpResponse.json(fake.state.rebalanceResult);
      }),
      http.post("/api/portfolio/refresh", async () => {
        await gate;
        return HttpResponse.json({
          as_of: "2026-10-20T10:00:00Z",
          fiat: "EUR",
          total_value: "999",
          cash: "999",
          cash_target_pct: "0",
          cash_weight_pct: null,
          holdings: [],
        });
      }),
      ...fake.handlers,
    ],
    client,
  );
  await user.click(
    await screen.findByRole("button", { name: "Rebalance now" }),
  );
  refreshAfter(client);
  await user.click(screen.getByRole("link", { name: "Settings" }));
  await user.click(await screen.findByRole("button", { name: "Sign out" }));
  await screen.findByRole("link", { name: "Sign in with Google" });
  release();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(router.state.location.pathname).toBe("/login");
  expect(
    client
      .getQueryCache()
      .getAll()
      .map((q) => q.queryKey),
  ).toEqual([["me"]]);
});

test("a pause or a refresh still in flight at sign out leaves nothing of the first user", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fake = platform();
  const client = createQueryClient();
  renderAt(
    "/",
    [
      http.post("/api/portfolio/refresh", async () => {
        await gate;
      }),
      http.patch("/api/config", async () => {
        await gate;
      }),
      ...fake.handlers,
    ],
    client,
  );
  await user.click(await screen.findByRole("button", { name: "Refresh" }));
  await user.click(screen.getByRole("link", { name: "Settings" }));
  await user.click(
    await screen.findByRole("switch", { name: "Pause everything" }),
  );
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByRole("link", { name: "Sign in with Google" });
  release();
  await waitFor(() =>
    expect(fake.requests.map((r) => `${r.method} ${r.path}`)).toEqual(
      expect.arrayContaining([
        "POST /api/portfolio/refresh",
        "PATCH /api/config",
      ]),
    ),
  );
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(
    client
      .getQueryCache()
      .getAll()
      .map((q) => q.queryKey),
  ).toEqual([["me"]]);
});
