import { expect, test } from "vitest";
import { refusalMessage } from "./keys";

test("an invalid key", () => {
  expect(refusalMessage({ rejection: "invalid_key" })).toBe(
    "Kraken did not accept this key. Check that both fields were copied in full.",
  );
});

test("missing permissions are listed", () => {
  expect(
    refusalMessage({
      rejection: "missing_permissions",
      missing: ["query-funds", "modify-trades"],
    }),
  ).toBe("The key is missing these permissions: query-funds, modify-trades.");
});

test("forbidden permissions are listed", () => {
  expect(
    refusalMessage({
      rejection: "forbidden_permissions",
      forbidden: ["withdraw-funds"],
    }),
  ).toBe(
    "The key can move funds out of the account (withdraw-funds). Create a new key without them.",
  );
});

test("a string, an unknown rejection or nothing is not a refusal", () => {
  expect(refusalMessage("kraken could not be reached")).toBeNull();
  expect(refusalMessage({ rejection: "something_new" })).toBeNull();
  expect(refusalMessage(undefined)).toBeNull();
  expect(refusalMessage([{ msg: "field required" }])).toBeNull();
});
