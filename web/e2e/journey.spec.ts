import { expect, test } from "@playwright/test";
import { mockApi, type Reply } from "./mockApi.js";

const ME = {
  id: "0b0f6c1e-6a58-4d8a-9d46-3c1f6f0f6b11",
  email: "ada@example.com",
  provider: "google",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const unauthorized: Reply = { status: 401, body: { detail: "unauthorized" } };

test("signed out, the application asks for a sign-in", async ({ page }) => {
  await mockApi(page, {
    "/api/auth/me": unauthorized,
    "/api/auth/refresh": unauthorized,
  });
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("link", { name: "Sign in with Google" }),
  ).toHaveAttribute("href", "/api/auth/login/google");
});

test("a refused sign-in is explained", async ({ page }) => {
  await mockApi(page, {
    "/api/auth/me": unauthorized,
    "/api/auth/refresh": unauthorized,
  });
  await page.goto("/login?error=google%20did%20not%20grant%20the%20login");
  await expect(page.getByRole("alert")).toHaveText(
    "google did not grant the login",
  );
});

test("a new user lands on the first onboarding step", async ({ page }) => {
  await mockApi(page, {
    "/api/auth/me": { status: 200, body: ME },
    "/api/config": { status: 404 },
    "/api/credentials/status": { status: 200, body: { registered: false } },
    "/api/assets": {
      status: 200,
      body: { assets: [], cash_target_pct: "0" },
    },
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding\/key$/);
  await expect(page.getByRole("heading", { name: "Kraken key" })).toBeVisible();
});

test("an onboarded user moves between the tabs", async ({ page }) => {
  await mockApi(page, {
    "/api/auth/me": { status: 200, body: ME },
    "/api/config": {
      status: 200,
      body: { onboarded_at: "2026-01-02T00:00:00Z", fiat: "EUR" },
    },
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
});

test("an expired session is renewed without leaving the page", async ({
  page,
}) => {
  let meCalls = 0;
  const calls = await mockApi(page, {
    "/api/auth/me": () =>
      ++meCalls === 1 ? unauthorized : { status: 200, body: ME },
    "/api/auth/refresh": { status: 200, body: {} },
    "/api/config": {
      status: 200,
      body: { onboarded_at: "2026-01-02T00:00:00Z", fiat: "EUR" },
    },
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  expect(
    calls.filter((call) => call === "POST /api/auth/refresh"),
  ).toHaveLength(1);
});
