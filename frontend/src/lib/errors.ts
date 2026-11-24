// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

// The one error shape the API answers in (F44-044, api/app/errors.py):
// {"detail": a sentence}, or, for a 422, {"detail": [{loc, msg, type}]}.
// This reads that shape and nothing else. Anything that is not it - a
// proxy's HTML page, an empty body - is never shown as it came; the
// status is.

interface ValidationError {
  loc?: unknown[];
  msg?: unknown;
}

function field(loc: unknown[] | undefined): string {
  const parts = (loc ?? []).filter((part) => part !== "body").map(String);
  return parts.join(".");
}

function fromList(detail: unknown[]): string | null {
  const lines = detail
    .filter((item): item is ValidationError => typeof item === "object" && item !== null)
    .map((item) => {
      const message = typeof item.msg === "string" ? item.msg : "";
      const where = field(item.loc);
      return where ? `${where}: ${message}` : message;
    })
    .filter((line) => line !== "");
  return lines.length > 0 ? lines.join("; ") : null;
}

/** What to tell a person about a failed request: the API's sentence, or
 * the status when the body is not in the API's one error shape. */
export function errorMessage(status: number, statusText: string, body: string): string {
  const fallback = statusText ? `${status} ${statusText}` : String(status);
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return fallback;
  }
  if (typeof parsed !== "object" || parsed === null || !("detail" in parsed)) {
    return fallback;
  }
  const detail = (parsed as { detail: unknown }).detail;
  if (typeof detail === "string" && detail.trim() !== "") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return fromList(detail) ?? fallback;
  }
  return fallback;
}
