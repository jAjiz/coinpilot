import { act, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test } from "vitest";
import { renderAt } from "@/test/render";

const handlers = [
  http.get("/api/auth/me", () =>
    HttpResponse.json({
      id: "u1",
      email: "a@b.c",
      provider: "google",
      status: "active",
    }),
  ),
  http.get("/api/config", () =>
    HttpResponse.json({ fiat: "EUR", onboarded_at: "2026-01-01T00:00:00Z" }),
  ),
  http.get("/api/portfolio", () =>
    HttpResponse.json({ detail: "no snapshot" }, { status: 404 }),
  ),
  http.get("/api/proposal", () =>
    HttpResponse.json({ detail: "no proposal" }, { status: 404 }),
  ),
];
const notice =
  "You're offline. Nothing can be sent until the connection is back.";

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

test("the shell has three tabs", async () => {
  renderAt("/", handlers);
  const nav = await screen.findByRole("navigation", { name: "Main" });
  expect(nav.querySelector('a[href="/"]')).toHaveTextContent("Home");
  expect(nav.querySelector('a[href="/history"]')).toHaveTextContent("History");
  expect(nav.querySelector('a[href="/settings"]')).toHaveTextContent(
    "Settings",
  );
});

test("the offline notice follows the connection", async () => {
  renderAt("/", handlers);
  await screen.findByRole("heading", { name: "Home" });
  expect(screen.queryByText(notice)).not.toBeInTheDocument();
  setOnline(false);
  expect(screen.getByText(notice)).toBeInTheDocument();
  setOnline(true);
  expect(screen.queryByText(notice)).not.toBeInTheDocument();
});
