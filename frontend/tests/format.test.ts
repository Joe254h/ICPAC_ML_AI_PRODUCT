import { expect, test } from "vitest";
import { UNAVAILABLE, day, num, signed, validDays } from "../lib/format";

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
  expect(day("2026-10-05")).toBe("05 Oct 2026");
});
