/** The one date-and-time format in the interface (Phase 32.1 review):
 * `4 Nov 2026, 18:18` — day, short month, year, 24-hour clock, in the
 * reader's local time. Unambiguous in every locale, which the
 * browser's own toLocaleString() is not (4/11 or 11/4?). No page formats a
 * date itself; a gate in scripts/check_frontend_tokens.py refuses
 * toLocaleString/toLocaleDateString/toLocaleTimeString outside this file.
 *
 * Built from the parts rather than Intl's formatter so the output is the
 * same in every browser and in the unit test (lib/datetime.test.ts). */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function asDate(value: string | Date): Date | null {
  const date = typeof value === "string" ? new Date(value) : value;
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `4 Nov 2026, 18:18`. An unparseable value is shown as it came, never as
 * "Invalid Date". */
export function formatDateTime(value: string | Date): string {
  const date = asDate(value);
  if (date === null) return String(value);
  return `${formatDate(date)}, ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** `4 Nov 2026`, for when only the day matters (an ingest key's creation). */
export function formatDate(value: string | Date): string {
  const date = asDate(value);
  if (date === null) return String(value);
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

/** `18:18`, for a time axis whose dates are shown elsewhere. */
export function formatTime(value: string | Date): string {
  const date = asDate(value);
  if (date === null) return String(value);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
