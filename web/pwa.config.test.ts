import { expect, test } from "vitest";
import { API_NAVIGATION, pwaOptions } from "./pwa.config.ts";

test.each([
  "/api",
  "/api/auth/login/google",
  "/api/auth/callback/google?code=x&state=y",
])("the service worker leaves %s to the network", (path) =>
  expect(API_NAVIGATION.test(path)).toBe(true),
);
test.each(["/", "/settings", "/onboarding/key", "/apiary"])(
  "the service worker answers %s with the shell",
  (path) => expect(API_NAVIGATION.test(path)).toBe(false),
);
test("nothing is cached at run time", () =>
  expect(pwaOptions.workbox?.runtimeCaching).toEqual([]));
test("no inline registration script", () =>
  expect(pwaOptions.injectRegister).toBe("script-defer"));
