// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

// F44-044 (Phase 44 batch 3): the API answers every error as
// {"detail": a sentence}, or a 422's list. The dashboard shows the
// sentence, never the raw JSON, and reads no other shape.

import assert from "node:assert/strict";
import { test } from "node:test";

import { errorMessage } from "./errors.ts";

test("a detail sentence is the message", () => {
  assert.equal(errorMessage(404, "Not Found", '{"detail":"no such agent"}'), "no such agent");
});

test("a 422's list names each field and what is wrong with it", () => {
  const body = JSON.stringify({
    detail: [
      { loc: ["body", "symptom"], msg: "Field required", type: "missing" },
      { loc: ["body", "environment"], msg: "String should have at least 1 character", type: "x" },
    ],
  });
  assert.equal(
    errorMessage(422, "Unprocessable Entity", body),
    "symptom: Field required; environment: String should have at least 1 character",
  );
});

test("any other shape is not shown, only the status", () => {
  assert.equal(
    errorMessage(429, "Too Many Requests", '{"error":"Rate limit exceeded: 10 per 1 minute"}'),
    "429 Too Many Requests",
  );
  assert.equal(errorMessage(502, "Bad Gateway", "<html>bad gateway</html>"), "502 Bad Gateway");
  assert.equal(errorMessage(500, "", ""), "500");
});
