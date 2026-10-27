import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import type { Config } from "@/api/queries";
import { fakePlatform } from "@/test/fakePlatform";
import { server } from "@/test/server";
import { createQueryClient } from "@/providers";
import { renderAt } from "@/test/render";

function platform(
  assets = [{ asset: "BTC", pair: "BTC/EUR", target_pct: "30" }],
) {
  return fakePlatform({
    registered: true,
    config: {
      fiat: "EUR",
      paused: false,
      onboarded_at: "2026-10-01T00:00:00Z",
    } as Config,
    assets,
    portfolio: {
      cash: "700",
      holdings: [
        {
          asset: "BTC",
          amount: "0.01",
          value: "300",
          locked: false,
        } as never,
      ],
    },
  });
}

test("the summary lists the targets, the cash and the fiat", async () => {
  renderAt("/settings", platform().handlers);
  expect(await screen.findByText("BTC 30 %")).toBeInTheDocument();
  expect(screen.getByText("Cash 70 %")).toBeInTheDocument();
  expect(
    screen.getByText("Currency: EUR. It cannot be changed."),
  ).toBeInTheDocument();
});

test("with no managed asset the summary says so", async () => {
  renderAt("/settings", platform([]).handlers);
  expect(
    await screen.findByText("No asset is managed yet."),
  ).toBeInTheDocument();
});

test("editing targets reads Kraken only when opened", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/settings", fake.handlers);
  await screen.findByText("BTC 30 %");
  expect(fake.requests).toEqual([]);
  await user.click(screen.getByRole("button", { name: "Edit targets" }));
  await screen.findByLabelText("Target for BTC");
  expect(
    fake.requests.filter((r) => r.path === "/api/portfolio/refresh"),
  ).toHaveLength(1);
});

test("a saved target shows in the summary", async () => {
  const user = userEvent.setup();
  renderAt("/settings", platform().handlers);
  await user.click(await screen.findByRole("button", { name: "Edit targets" }));
  const input = await screen.findByLabelText("Target for BTC");
  await user.clear(input);
  await user.type(input, "35");
  await user.click(screen.getByRole("button", { name: "Save targets" }));
  expect(await screen.findByText("BTC 35 %")).toBeInTheDocument();
  expect(screen.getByText("Cash 65 %")).toBeInTheDocument();
  expect(screen.queryByLabelText("Target for BTC")).not.toBeInTheDocument();
});

test("cancel sends nothing", async () => {
  const user = userEvent.setup();
  const fake = platform();
  renderAt("/settings", fake.handlers);
  await user.click(await screen.findByRole("button", { name: "Edit targets" }));
  await screen.findByLabelText("Target for BTC");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("BTC 30 %")).toBeInTheDocument();
  expect(
    fake.requests.filter((r) => r.path !== "/api/portfolio/refresh"),
  ).toEqual([]);
});

test("a failed refetch keeps the open form and its edits", async () => {
  const user = userEvent.setup();
  const fake = platform();
  const { client } = { client: createQueryClient() };
  renderAt("/settings", fake.handlers, client);
  await user.click(await screen.findByRole("button", { name: "Edit targets" }));
  const input = await screen.findByLabelText("Target for BTC");
  await user.clear(input);
  await user.type(input, "35");
  server.use(
    http.get("/api/assets", () =>
      HttpResponse.json({ detail: "platform down" }, { status: 503 }),
    ),
  );
  await client.invalidateQueries({ queryKey: ["assets"] });
  await waitFor(() =>
    expect(client.getQueryState(["assets"])?.status).toBe("error"),
  );
  expect(screen.getByLabelText("Target for BTC")).toHaveValue("35");
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});
