import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDate, formatDateTime, formatTime } from "./datetime.ts";

// Local time, built from parts, so the test holds in every timezone the
// suite runs in.
const evening = new Date(2026, 10, 4, 18, 18, 42);
const morning = new Date(2026, 0, 9, 7, 5);

test("a date and time read as day, short month, year and a 24-hour clock", () => {
  assert.equal(formatDateTime(evening), "4 Nov 2026, 18:18");
  assert.equal(formatDateTime(morning), "9 Jan 2026, 07:05");
});

test("an ISO string from the API is shown in local time", () => {
  assert.equal(formatDateTime(evening.toISOString()), "4 Nov 2026, 18:18");
});

test("midnight is 00:00, not 24:00 or 12 AM", () => {
  assert.equal(formatTime(new Date(2026, 10, 4, 0, 0)), "00:00");
});

test("a date alone has no time", () => {
  assert.equal(formatDate(morning), "9 Jan 2026");
});

test("an unparseable value is shown as given, never as Invalid Date", () => {
  assert.equal(formatDateTime("not a date"), "not a date");
});
