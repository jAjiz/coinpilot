import { expect, test } from "vitest";
import {
  cadencePatch,
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
  const custom = { kind: "custom" };
  const noon = investFields("daily", "2026-03-29").cadence_anchor;
  expect(
    readRebalance({
      mode: "MIN",
      interval_days: null,
      interval_months: null,
      cadence_anchor: null,
    }),
  ).toEqual(custom);
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
  ).toEqual(custom);
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
  ).toEqual(custom);
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
  ).toEqual(custom);
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
  ).toEqual(custom);
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
