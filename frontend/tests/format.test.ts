import { expect, test } from "vitest";
import {
  UNAVAILABLE,
  day,
  num,
  period,
  shortPeriod,
  signed,
  validDays,
  weekPeriod,
} from "../lib/format";

test("missing values are shown as unavailable, never as zero", () => {
  expect(num(null)).toBe(UNAVAILABLE);
  expect(num(undefined)).toBe(UNAVAILABLE);
  expect(num(Number.NaN)).toBe(UNAVAILABLE);
  expect(signed(null)).toBe(UNAVAILABLE);
  expect(day(undefined)).toBe(UNAVAILABLE);
});

test("numbers keep their precision and sign", () => {
  expect(num(6.97012, 2)).toBe("6.97");
  expect(num(0)).toBe("0.0");
  expect(signed(-0.2897, 2)).toBe("−0.29");
  expect(signed(25.5)).toBe("+25.5");
});

test("the Week-2 window ends the day before valid_end (00 UTC)", () => {
  expect(
    validDays("2026-10-12T00:00:00+00:00", "2026-10-19T00:00:00+00:00"),
  ).toBe("12 Oct 2026 – 18 Oct 2026");
  expect(day("2026-10-05")).toBe("5 Oct 2026");
});

test("short periods leave out the year", () => {
  expect(shortPeriod("2026-09-21", "2026-09-30")).toBe("21–30 Sep");
  expect(shortPeriod("2026-09-28", "2026-10-04")).toBe("28 Sep – 4 Oct");
});

test("periods read as headlines", () => {
  expect(period("2026-10-14", "2026-10-20")).toBe("14–20 October 2026");
  expect(period("2026-09-28", "2026-10-04")).toBe(
    "28 September – 4 October 2026",
  );
  expect(period("2026-12-28", "2027-01-03")).toBe(
    "28 December 2026 – 3 January 2027",
  );
  expect(
    weekPeriod("2026-10-14T00:00:00+00:00", "2026-10-21T00:00:00+00:00"),
  ).toBe("14–20 October 2026");
});
