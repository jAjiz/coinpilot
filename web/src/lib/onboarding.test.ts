import { expect, test } from "vitest";
import { onboardingStep, reachableSteps } from "./onboarding";

test.each([
  [{ keyRegistered: false, fiat: null, assetCount: 0 }, "key"],
  [{ keyRegistered: false, fiat: "EUR", assetCount: 2 }, "key"],
  [{ keyRegistered: true, fiat: null, assetCount: 0 }, "portfolio"],
  [{ keyRegistered: true, fiat: "EUR", assetCount: 0 }, "portfolio"],
  [{ keyRegistered: true, fiat: "EUR", assetCount: 2 }, "automation"],
] as const)("the first step for %o is %s", (state, step) => {
  expect(onboardingStep(state)).toBe(step);
});

test.each([
  ["key", ["key"]],
  ["portfolio", ["key", "portfolio"]],
  ["automation", ["key", "portfolio", "automation", "summary"]],
] as const)("from %s the reachable steps are %o", (first, steps) => {
  expect(reachableSteps(first)).toEqual(steps);
});
