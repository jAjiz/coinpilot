import { expect, test } from "vitest";
import { ApiError } from "./client";
import { isLostAnswer } from "./operations";

test("a failed fetch and a 500, 502 or 504 are lost answers; a 503, 409 or 422 are not", () => {
  expect(isLostAnswer(new TypeError("Failed to fetch"))).toBe(true);
  for (const status of [500, 502, 504]) {
    expect(isLostAnswer(new ApiError(status, "down", null))).toBe(true);
  }
  for (const status of [503, 409, 422]) {
    expect(isLostAnswer(new ApiError(status, "answered", null))).toBe(false);
  }
});
