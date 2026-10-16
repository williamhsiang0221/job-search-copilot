import type { RangePreset } from "./types";

/** Parses an ISO date string for local display.
 *
 * A date-only string ("2026-08-29", from a SQL Date column) has no time
 * component, so per spec `new Date(...)` treats it as UTC midnight —
 * converting that to any timezone behind UTC (all of the Americas included)
 * rolls the displayed calendar date back a day.
 *
 * A full timestamp from this backend (fetched_at, normalized_at, created_at,
 * ...) is `datetime.isoformat()` on a value that started as UTC-aware but
 * lost its tzinfo on the round trip through SQLite — so it arrives with no
 * trailing "Z"/offset at all. Per spec, a date-time string with no timezone
 * designator is parsed as *local* time, not UTC, so without correction the
 * wall-clock numbers get taken at face value instead of converted — wrong by
 * exactly the local UTC offset, which rolls the displayed date forward or
 * back a day for anything near a UTC midnight boundary. Append "Z" whenever
 * no designator is present so it parses as the UTC instant it actually is.
 */
export function parseIsoDate(iso: string): Date {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  if (dateOnly) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}

/** Formats a Date as "YYYY-MM-DD" using its local calendar fields — never
 * `toISOString()`, which converts to UTC first and is the same off-by-one
 * risk `parseIsoDate` exists to avoid, just in the opposite direction. */
export function toIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Today's date, local. */
export function todayIso(): string {
  return toIsoDate(new Date());
}

/** The Monday on or before this date, as an ISO date string — a stable,
 * sortable bucket key for "which week." */
export function mondayOfIso(iso: string): string {
  const date = parseIsoDate(iso);
  const day = date.getDay(); // 0 = Sunday, 1 = Monday, ... 6 = Saturday
  const offset = (day + 6) % 7; // days since the most recent Monday
  date.setDate(date.getDate() - offset);
  return toIsoDate(date);
}

/** This date, n days earlier, as an ISO date string. */
export function daysBeforeIso(iso: string, days: number): string {
  const date = parseIsoDate(iso);
  date.setDate(date.getDate() - days);
  return toIsoDate(date);
}

/** Turns a dropdown preset into an inclusive calendar-day range, the same
 * semantics as the backend's resolve_range in main.py (kept in sync by hand
 * — there is no shared source between a Python API and a TS frontend). */
export function resolveRangePreset(
  preset: RangePreset,
  customStart?: string,
  customEnd?: string,
): { start: string; end: string } {
  const today = todayIso();
  switch (preset) {
    case "today":
      return { start: today, end: today };
    case "yesterday": {
      const yesterday = daysBeforeIso(today, 1);
      return { start: yesterday, end: yesterday };
    }
    case "past3":
      return { start: daysBeforeIso(today, 2), end: today };
    case "past7":
      return { start: daysBeforeIso(today, 6), end: today };
    case "custom":
      return { start: customStart ?? today, end: customEnd ?? today };
  }
}
