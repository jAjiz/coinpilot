import { expect, test } from "vitest";
import {
  anchorFromInput,
  anchorInput,
  cadencePatch,
  checkCustom,
  localDate,
  readInvest,
  readRebalance,
  investFields,
  rebalanceFields,
  type InvestChoice,
  type RebalanceChoice,
} from "./cadence";

test("the test zone is Madrid", () => {
  expect(new Date("2026-07-01T10:00:00Z").getHours()).toBe(12);
});

test("noon in summer time is 10:00 UTC", () => {
  expect(investFields("weekly", "2026-10-19")).toEqual({
    mode: "INTERVAL",
    interval_days: 7,
    interval_months: null,
    cadence_anchor: "2026-10-19T10:00:00.000Z",
  });
});

test("noon in winter time is 11:00 UTC", () => {
  expect(investFields("monthly", "2026-12-01").cadence_anchor).toBe(
    "2026-12-01T11:00:00.000Z",
  );
});

test("the day the clocks change keeps noon local", () => {
  expect(investFields("daily", "2026-10-25").cadence_anchor).toBe(
    "2026-10-25T11:00:00.000Z",
  );
});

test("the 31st is sent as the 31st", () => {
  expect(rebalanceFields("monthly", "2026-01-31")).toEqual({
    mode: "INTERVAL",
    interval_days: null,
    interval_months: 1,
    cadence_anchor: "2026-01-31T11:00:00.000Z",
  });
});

test("a date in the past is kept", () => {
  expect(investFields("daily", "2020-02-29").cadence_anchor).toBe(
    "2020-02-29T11:00:00.000Z",
  );
});

test("as soon as possible has no anchor", () => {
  expect(investFields("asap", "2026-03-29")).toEqual({
    mode: "MIN",
    interval_days: null,
    interval_months: null,
    cadence_anchor: null,
  });
});

test("every choice reads back as itself", () => {
  const date = "2026-03-29";
  const invest: InvestChoice[] = ["asap", "daily", "weekly", "monthly"];
  for (const choice of invest) {
    expect(readInvest(investFields(choice, date), date)).toEqual({
      kind: "choice",
      choice,
      date,
    });
  }
  const rebalance: RebalanceChoice[] = [
    "monthly",
    "quarterly",
    "half-yearly",
    "yearly",
  ];
  for (const choice of rebalance) {
    expect(readRebalance(rebalanceFields(choice, date))).toEqual({
      kind: "choice",
      choice,
      date,
    });
  }
});

test("a cadence the select cannot express is custom", () => {
  const noon = investFields("daily", "2026-03-29").cadence_anchor;
  expect(
    readRebalance({
      mode: "MIN",
      interval_days: null,
      interval_months: null,
      cadence_anchor: null,
    }),
  ).toMatchObject({ kind: "custom" });
  expect(
    readInvest(
      {
        mode: "INTERVAL",
        interval_days: 2,
        interval_months: null,
        cadence_anchor: noon,
      },
      "2026-03-29",
    ),
  ).toMatchObject({ kind: "custom" });
  expect(
    readInvest(
      {
        mode: "INTERVAL",
        interval_days: 1,
        interval_months: 1,
        cadence_anchor: noon,
      },
      "2026-03-29",
    ),
  ).toMatchObject({ kind: "custom" });
  expect(
    readInvest(
      {
        mode: "INTERVAL",
        interval_days: 1,
        interval_months: null,
        cadence_anchor: new Date(2026, 2, 29, 9).toISOString(),
      },
      "2026-03-29",
    ),
  ).toMatchObject({ kind: "custom" });
  expect(
    readInvest(
      {
        mode: "INTERVAL",
        interval_days: 1,
        interval_months: null,
        cadence_anchor: null,
      },
      "2026-03-29",
    ),
  ).toMatchObject({ kind: "custom" });
});

test("today is the local date", () => {
  expect(localDate(new Date("2026-10-19T22:30:00Z"))).toBe("2026-10-20");
});

test("the patch names the prefix's fields", () => {
  const patch = cadencePatch(
    "rebalance",
    rebalanceFields("quarterly", "2026-10-01"),
  );
  expect(patch).toMatchObject({
    rebalance_cadence_mode: "INTERVAL",
    rebalance_interval_months: 3,
    rebalance_interval_days: null,
  });
});

test("the anchor round-trips through the local input", () => {
  expect(anchorInput("2026-10-27T11:00:00.000Z")).toBe("2026-10-27T12:00");
  expect(anchorFromInput("2026-10-27T12:00")).toBe("2026-10-27T11:00:00.000Z");
  expect(anchorInput(null)).toBe("");
  expect(anchorFromInput("")).toBeNull();
  expect(anchorFromInput("2026-02-31T12:00")).toBeNull();
});

test("the anchor input crosses daylight saving", () => {
  expect(anchorInput("2026-07-01T10:00:00.000Z")).toBe("2026-07-01T12:00");
  expect(anchorFromInput("2026-07-01T12:00")).toBe("2026-07-01T10:00:00.000Z");
});

test("custom checks name the field at fault", () => {
  const ok = {
    mode: "INTERVAL" as const,
    interval_days: 10,
    interval_months: null,
    cadence_anchor: "2026-10-27T11:00:00.000Z",
  };
  expect(checkCustom(ok)).toEqual({ days: null, months: null, anchor: null });
  expect(checkCustom({ ...ok, interval_days: 3651 }).days).toBe(
    "Enter whole days from 0 to 3650.",
  );
  expect(checkCustom({ ...ok, interval_days: 1.5 }).days).toBe(
    "Enter whole days from 0 to 3650.",
  );
  expect(checkCustom({ ...ok, interval_days: NaN }).days).toBe(
    "Enter whole days from 0 to 3650.",
  );
  expect(checkCustom({ ...ok, interval_months: 121 }).months).toBe(
    "Enter whole months from 0 to 120.",
  );
  expect(
    checkCustom({ ...ok, interval_days: 0, interval_months: 0 }).days,
  ).toBe("Choose at least one day or one month.");
  expect(checkCustom({ ...ok, cadence_anchor: null }).anchor).toBe(
    "Choose when it starts.",
  );
  expect(
    checkCustom({
      ...ok,
      mode: "MIN",
      interval_days: -1,
      cadence_anchor: null,
    }),
  ).toEqual({ days: null, months: null, anchor: null });
});

test("a cadence read that the select cannot express keeps its fields", () => {
  const fields = {
    mode: "INTERVAL" as const,
    interval_days: 10,
    interval_months: null,
    cadence_anchor: "2026-10-27T11:00:00.000Z",
  };
  expect(readInvest(fields, "2026-10-27")).toEqual({ kind: "custom", fields });
  expect(readRebalance(fields)).toEqual({ kind: "custom", fields });
});
