import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import type { Config } from "@/api/queries";
import { meKey, onboardingKey } from "@/features/auth/session";
import { createQueryClient } from "@/providers";
import { renderAt } from "@/test/render";
import { fakePlatform } from "@/test/fakePlatform";

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillKey(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("API key"), "the-key");
  await user.type(screen.getByLabelText("Private key"), "the-secret");
}

function refuse(status: number, body: unknown) {
  return fakePlatform({ keyReply: { status, body } });
}

test("the four permissions are listed, with the withdrawal warning", async () => {
  renderAt("/onboarding/key", fakePlatform().handlers);
  await screen.findByLabelText("API key");
  expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
  expect(
    screen.getByText(/open Settings → API and create a key/),
  ).toBeInTheDocument();
  for (const [label, code] of [
    ["Query Funds", "query-funds"],
    ["Query Open Orders & Trades", "query-open-trades"],
    ["Query Closed Orders & Trades", "query-closed-trades"],
    ["Create & Modify Orders", "modify-trades"],
  ]) {
    const item = screen.getByText(label, { exact: false, selector: "li" });
    expect(item).toHaveTextContent(`${label} ${code}`);
  }
  expect(
    screen.getByText(
      "Never enable withdrawal permissions. CoinPilot refuses a key that can move funds out.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Back" })).not.toBeInTheDocument();
});

test("both fields are visible, untouched by the keyboard, and say which Kraken value goes where", async () => {
  renderAt("/onboarding/key", fakePlatform().handlers);
  for (const [label, hint] of [
    ["API key", "Kraken's “API Key”: the shorter value."],
    ["Private key", "Kraken's “Private Key”: the longer value."],
  ]) {
    const field = await screen.findByLabelText(label);
    expect(field).toHaveAttribute("type", "text");
    expect(field).toHaveAttribute("autocomplete", "off");
    expect(field).toHaveAttribute("autocapitalize", "none");
    expect(field).toHaveAttribute("autocorrect", "off");
    expect(field).toHaveAttribute("spellcheck", "false");
    expect(field).toHaveAccessibleDescription(hint);
  }
});

test("an accepted key moves on to the portfolio", async () => {
  const user = userEvent.setup();
  const platform = fakePlatform();
  const router = renderAt("/onboarding/key", platform.handlers);
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText("Key saved.");
  expect(screen.queryByText(/also has permissions/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Restrict the key/)).not.toBeInTheDocument();
  expect(platform.requests).toEqual([
    {
      method: "POST",
      path: "/api/credentials",
      body: { api_key: "the-key", api_secret: "the-secret" },
    },
  ]);
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Portfolio" });
  expect(router.state.location.pathname).toBe("/onboarding/portfolio");
});

test("the fields are emptied once the key is accepted", async () => {
  const user = userEvent.setup();
  renderAt("/onboarding/key", fakePlatform().handlers);
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText("Key saved.");
  expect(screen.getByLabelText("API key")).toHaveValue("");
  expect(screen.getByLabelText("Private key")).toHaveValue("");
});

test("the secret is kept nowhere once the request is done", async () => {
  const user = userEvent.setup();
  const client = createQueryClient();
  renderAt("/onboarding/key", fakePlatform().handlers, client);
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText("Key saved.");
  const kept = JSON.stringify([
    client
      .getMutationCache()
      .getAll()
      .map((m) => [m.state, m.options]),
    client
      .getQueryCache()
      .getAll()
      .map((q) => q.state),
  ]);
  expect(kept).not.toContain("the-secret");
  expect(kept).not.toContain("the-key");
});

test("extra permissions and a missing IP restriction are pointed out", async () => {
  const user = userEvent.setup();
  renderAt(
    "/onboarding/key",
    fakePlatform({
      keyReply: {
        status: 201,
        body: {
          validated_at: "2026-10-20T09:00:00Z",
          permissions: ["query-funds"],
          ip_allowlist: [],
          unnecessary: ["query-ledger"],
        },
      },
    }).handlers,
  );
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  await screen.findByText(
    "This key also has permissions CoinPilot does not need: query-ledger. Turn them off in Kraken.",
  );
  expect(
    screen.getByText(
      "Restrict the key to your server's IP address in Kraken, so that it is useless anywhere else.",
    ),
  ).toBeInTheDocument();
});

test("a refused key shows the platform's reason", async () => {
  const user = userEvent.setup();
  const router = renderAt(
    "/onboarding/key",
    refuse(422, {
      detail: {
        rejection: "missing_permissions",
        missing: ["query-closed-trades"],
        forbidden: [],
        unnecessary: [],
      },
    }).handlers,
  );
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The key is missing these permissions: query-closed-trades.",
  );
  expect(router.state.location.pathname).toBe("/onboarding/key");
  expect(screen.getByLabelText("API key")).toHaveValue("the-key");
  expect(screen.getByLabelText("Private key")).toHaveValue("the-secret");
});

test("a key that can withdraw is refused, naming the permissions", async () => {
  const user = userEvent.setup();
  renderAt(
    "/onboarding/key",
    refuse(422, {
      detail: {
        rejection: "forbidden_permissions",
        missing: [],
        forbidden: ["withdraw-funds", "withdraw-export"],
        unnecessary: [],
      },
    }).handlers,
  );
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The key can move funds out of the account (withdraw-funds, withdraw-export). Create a new key without them.",
  );
});

test("a key Kraken does not know is refused", async () => {
  const user = userEvent.setup();
  renderAt(
    "/onboarding/key",
    refuse(422, { detail: { rejection: "invalid_key" } }).handlers,
  );
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Kraken did not accept this key. Check that both fields were copied in full.",
  );
});

test("an unreachable Kraken says nothing was changed", async () => {
  const user = userEvent.setup();
  renderAt(
    "/onboarding/key",
    refuse(503, {
      detail: "kraken could not be reached; the key was not stored",
    }).handlers,
  );
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Kraken didn't answer; nothing was changed.",
  );
});

test("the button is disabled while verifying", async () => {
  const user = userEvent.setup();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  renderAt("/onboarding/key", [
    http.post("/api/credentials", async () => {
      await gate;
      return HttpResponse.json({ detail: "slow" }, { status: 503 });
    }),
    ...fakePlatform().handlers,
  ]);
  await fillKey(user);
  await user.click(screen.getByRole("button", { name: "Verify & save" }));
  expect(
    await screen.findByRole("button", { name: "Verifying with Kraken…" }),
  ).toBeDisabled();
  release();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Verify & save" })).toBeEnabled(),
  );
});

test("the button is disabled while offline", async () => {
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
  renderAt("/onboarding/key", fakePlatform().handlers);
  await screen.findByLabelText("API key");
  expect(screen.getByRole("button", { name: "Verify & save" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("You're offline");
});

test("Continue is disabled while offline", async () => {
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
  renderAt(
    "/onboarding/key",
    fakePlatform({
      registered: true,
      config: { fiat: "EUR", onboarded_at: null } as Config,
    }).handlers,
  );
  expect(
    await screen.findByRole("button", { name: "Continue" }),
  ).toBeDisabled();
});

test("a saved key can be kept", async () => {
  const user = userEvent.setup();
  const config = { fiat: "EUR", onboarded_at: null } as Config;
  const router = renderAt(
    "/onboarding/key",
    fakePlatform({ registered: true, config }).handlers,
  );
  await screen.findByText(/A key is saved, verified on/);
  expect(screen.getByText(/verified on 20 October 2026/)).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Replace the key" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Portfolio" });
  expect(router.state.location.pathname).toBe("/onboarding/portfolio");
});

test("a step that cannot load says why and tries again", async () => {
  const user = userEvent.setup();
  // the gate's state is cached, so only the step's own query goes to the platform
  const client = createQueryClient();
  client.setQueryData(meKey, {
    id: "u1",
    email: "a@b.c",
    provider: "google",
    status: "active",
  });
  client.setQueryData(onboardingKey, { onboarded: false, step: "key" });
  let down = true;
  renderAt(
    "/onboarding/key",
    [
      http.get("/api/credentials/status", () =>
        down
          ? HttpResponse.json({ detail: "platform down" }, { status: 503 })
          : HttpResponse.json({ registered: false }),
      ),
      ...fakePlatform().handlers,
    ],
    client,
  );
  await screen.findByText("platform down");
  down = false;
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByLabelText("API key");
});
