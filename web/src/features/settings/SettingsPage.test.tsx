import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { approveKey, investKey } from "@/api/operations";
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
    screen.getByText(/While paused, nothing runs on schedule/),
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
