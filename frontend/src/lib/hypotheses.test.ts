import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { HYPOTHESIS_LABELS, hypothesisLabel } from "./hypotheses.ts";

const FIXTURE = path.resolve(import.meta.dirname, "../../../shared/tests/investigation_conformance.json");
const labels = (JSON.parse(readFileSync(FIXTURE, "utf-8")) as { hypothesis_labels: Record<string, string> })
  .hypothesis_labels;
const kinds = Object.keys(labels);

test("every hypothesis kind in the shared model has a label", () => {
  assert.ok(kinds.length > 0, "the shared fixture lists no hypothesis kinds");
  const unlabelled = kinds.filter((kind) => !(kind in HYPOTHESIS_LABELS));
  assert.deepEqual(unlabelled, [], `kinds with no label in lib/hypotheses.ts: ${unlabelled.join(", ")}`);
});

test("no label is kept for a kind the model no longer has", () => {
  const stale = Object.keys(HYPOTHESIS_LABELS).filter((kind) => !kinds.includes(kind));
  assert.deepEqual(stale, []);
});

test("every label is the shared map's own word for it", () => {
  // The fixture's hypothesis_labels is the one source; the Go binary
  // carries the same copy under the same test.
  assert.deepEqual({ ...HYPOTHESIS_LABELS }, labels);
});

test("the audience kind reads as words", () => {
  assert.equal(hypothesisLabel("auth_audience_mismatch"), "Auth audience mismatch");
});

test("an unknown kind still reads as words, never blank", () => {
  assert.equal(hypothesisLabel("queue_backlogged"), "Queue backlogged");
});
