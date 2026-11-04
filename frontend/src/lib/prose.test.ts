import assert from "node:assert/strict";
import { test } from "node:test";

import { splitFlags } from "./prose.ts";

test("a flag in a sentence is split out as code", () => {
  assert.deepEqual(splitFlags("no reference environment was named (--reference)"), [
    { kind: "text", text: "no reference environment was named (" },
    { kind: "flag", text: "--reference" },
    { kind: "text", text: ")" },
  ]);
});

test("a flag with a value keeps its value", () => {
  assert.deepEqual(splitFlags("run with --fail-on=breaks_request_path."), [
    { kind: "text", text: "run with " },
    { kind: "flag", text: "--fail-on=breaks_request_path" },
    { kind: "text", text: "." },
  ]);
});

test("several flags, and text with none", () => {
  assert.deepEqual(
    splitFlags("--from web and --no-plugins").map((p) => p.kind),
    ["flag", "text", "flag"],
  );
  assert.deepEqual(splitFlags("nothing to see"), [{ kind: "text", text: "nothing to see" }]);
});

test("a double dash that is not a flag stays text", () => {
  assert.deepEqual(splitFlags("8.2.0--8.2.2 and a -- b"), [{ kind: "text", text: "8.2.0--8.2.2 and a -- b" }]);
});
