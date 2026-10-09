/** Display helpers. A missing value is shown as unavailable, never as zero. */
export const UNAVAILABLE = "Unavailable";

export function num(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value)
    ? UNAVAILABLE
    : value.toLocaleString("en-GB", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
}

export function signed(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return (
    (value > 0 ? "+" : value < 0 ? "−" : "") + num(Math.abs(value), digits)
  );
}

const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function day(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  const date = new Date(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  return Number.isNaN(date.getTime()) ? UNAVAILABLE : DAY.format(date);
}

/** Week-2 window: valid_end is the 00 UTC instant after the last day (Days 8-14). */
export function validDays(start: string, end: string): string {
  const first = new Date(start);
  const last = new Date(new Date(end).getTime() - 86_400_000);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()))
    return UNAVAILABLE;
  return `${DAY.format(first)} – ${DAY.format(last)}`;
}

const MONTH_YEAR = new Intl.DateTimeFormat("en-GB", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const DAY_MONTH = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});

/**
 * A period as a headline, e.g. "14–20 October 2026" or "28 September – 4 October 2026".
 * ``end`` is the last day itself (inclusive); see validDays for Week-2 windows.
 */
export function period(start: string, end: string): string {
  const first = new Date(start.length === 10 ? start + "T00:00:00Z" : start);
  const last = new Date(end.length === 10 ? end + "T00:00:00Z" : end);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()))
    return UNAVAILABLE;
  const sameYear = first.getUTCFullYear() === last.getUTCFullYear();
  if (sameYear && first.getUTCMonth() === last.getUTCMonth())
    return `${first.getUTCDate()}–${last.getUTCDate()} ${MONTH_YEAR.format(last)}`;
  if (sameYear)
    return `${DAY_MONTH.format(first)} – ${DAY_MONTH.format(last)} ${last.getUTCFullYear()}`;
  return `${DAY_MONTH.format(first)} ${first.getUTCFullYear()} – ${DAY_MONTH.format(last)} ${last.getUTCFullYear()}`;
}

const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");

/** A period without its year, for tight spaces, e.g. "21–30 Sep" or "28 Sep – 4 Oct". */
export function shortPeriod(start: string, end: string): string {
  const first = new Date(start.length === 10 ? start + "T00:00:00Z" : start);
  const last = new Date(end.length === 10 ? end + "T00:00:00Z" : end);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()))
    return UNAVAILABLE;
  return first.getUTCMonth() === last.getUTCMonth()
    ? `${first.getUTCDate()}–${last.getUTCDate()} ${MONTHS[last.getUTCMonth()]}`
    : `${first.getUTCDate()} ${MONTHS[first.getUTCMonth()]} – ${last.getUTCDate()} ${MONTHS[last.getUTCMonth()]}`;
}

/** A Week-2 window (valid_end exclusive) as a headline period. */
export function weekPeriod(start: string, end: string): string {
  const last = new Date(new Date(end).getTime() - 86_400_000).toISOString();
  return period(start, last);
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? UNAVAILABLE
    : date.toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
        timeZoneName: "short",
      });
}

export function shortHash(value: unknown, length = 12): string {
  return typeof value === "string" && value
    ? value.slice(0, length)
    : UNAVAILABLE;
}

export const SERIES = {
  raw: { label: "Raw ECMWF", token: "--series-raw" },
  mbc: { label: "MBC", token: "--series-mbc" },
  hybrid: { label: "MBC + AI/ML", token: "--series-hybrid" },
} as const;

export type SeriesKey = keyof typeof SERIES;
