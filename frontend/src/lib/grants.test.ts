import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { diffGrants, GRANT_WORDS, INVESTIGATION_NEEDS, missingForInvestigation } from "./grants.ts";

const FIXTURE = path.resolve(import.meta.dirname, "../../../shared/tests/capability_conformance.json");
const capabilities = (
  JSON.parse(readFileSync(FIXTURE, "utf-8")) as { capabilities: { name: string }[] }
).capabilities.map((c) => c.name);

test("every capability in the shared vocabulary has words", () => {
  assert.ok(capabilities.length > 0);
  const unworded = capabilities.filter((name) => !(name in GRANT_WORDS));
  assert.deepEqual(unworded, [], `no words in lib/grants.ts for: ${unworded.join(", ")}`);
});

test("no words are kept for a capability that no longer exists", () => {
  const stale = Object.keys(GRANT_WORDS).filter((name) => !capabilities.includes(name));
  assert.deepEqual(stale, []);
});

test("what an investigation needs is the documented reachability set", () => {
  const doc = readFileSync(path.resolve(import.meta.dirname, "../../../docs/PERMISSIONS.md"), "utf-8");
  const row = doc.split(/\r?\n/).find((line) => line.startsWith("| reachability |"));
  assert.ok(row, "docs/PERMISSIONS.md has no reachability row");
  const documented = [...row.split("|")[2].matchAll(/`([^`]+)`/g)].map((m) => m[1]).sort();
  assert.deepEqual([...INVESTIGATION_NEEDS].sort(), documented);
});

test("an allowance change is shown as what is added and what is taken away", () => {
  assert.deepEqual(diffGrants(["net.tcp.connect", "net.dns.resolve"], ["net.tcp.connect", "net.http.outbound"]), {
    added: ["net.http.outbound"],
    removed: ["net.dns.resolve"],
    kept: ["net.tcp.connect"],
  });
});

test("a missing grant is either one to allow or one the agent does not hold", () => {
  assert.deepEqual(missingForInvestigation(["net.tcp.connect", "net.http.outbound"], ["net.tcp.connect"]), {
    notAllowed: ["net.http.outbound"],
    notHeld: [],
  });
  assert.deepEqual(missingForInvestigation(["net.tcp.connect"], ["net.tcp.connect"]), {
    notAllowed: [],
    notHeld: ["net.http.outbound"],
  });
  assert.deepEqual(missingForInvestigation([...INVESTIGATION_NEEDS], [...INVESTIGATION_NEEDS]), {
    notAllowed: [],
    notHeld: [],
  });
});
