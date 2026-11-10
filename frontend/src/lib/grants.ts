/** Every capability an agent can report or be allowed, in plain words
 * (Phase 33 part 3: "grants shown in plain language"). Held to the shared
 * vocabulary — shared/tests/capability_conformance.json, which the Go CLI
 * and the Python model both read — by grants.test.ts: a capability with no
 * words here, or words for one that no longer exists, fails it. */
export const GRANT_WORDS: Record<string, string> = {
  "model.read": "Read the system model",
  "repo.read": "Read the repository it was given",
  "config.read.names": "See which configuration keys are set — names only, never values",
  "config.read.values": "Read and store the value of the listed configuration keys",
  "config.inspect.values": "Inspect the listed keys' values in memory, to check a token's audience — never stored",
  "db.metadata.read": "Connect to databases read-only and read their schema — never a row",
  "db.rows.read": "Read rows from the listed tables",
  "net.dns.resolve": "Resolve host names",
  "net.tcp.connect": "Open a TCP connection and close it, sending nothing",
  "net.tls.inspect": "Complete a TLS handshake to check a certificate",
  "net.http.outbound": "Send read-only HTTP requests (GET, OPTIONS) to services",
  "telemetry.logs.read": "Read logs",
  "telemetry.metrics.read": "Read metrics",
  "telemetry.traces.read": "Read traces",
  "deploy.metadata.read": "Read deployment metadata: images, digests, replica counts",
  "process.exec.allowlist": "Run the listed read-only commands",
};

/** What an agent must be allowed for an investigation to test a request
 * path at all: the reachability set in docs/PERMISSIONS.md ("The minimum
 * grants for each kind of investigation"). With less, the walk could not
 * tell whether a connection or a service fails, so the dashboard starts
 * nothing and says why. */
export const INVESTIGATION_NEEDS = ["net.tcp.connect", "net.http.outbound"] as const;

export function grantWords(name: string): string {
  return GRANT_WORDS[name] ?? name;
}

export interface GrantDiff {
  added: string[];
  removed: string[];
  kept: string[];
}

/** An allowance change, as the screen shows it before it is saved. */
export function diffGrants(before: readonly string[], after: readonly string[]): GrantDiff {
  const was = new Set(before);
  const now = new Set(after);
  return {
    added: [...now].filter((grant) => !was.has(grant)).sort(),
    removed: [...was].filter((grant) => !now.has(grant)).sort(),
    kept: [...now].filter((grant) => was.has(grant)).sort(),
  };
}

/** The grants an agent may use in an environment for an investigation it
 * is asked to run: its allowance there, which is only ever inside what it
 * reports. Returns the needed grants it lacks, and which of those it does
 * report (so an admin can allow them) and which it does not hold at all. */
export function missingForInvestigation(
  reported: readonly string[],
  allowed: readonly string[],
): { notAllowed: string[]; notHeld: string[] } {
  const notAllowed: string[] = [];
  const notHeld: string[] = [];
  for (const grant of INVESTIGATION_NEEDS) {
    if (allowed.includes(grant)) continue;
    if (reported.includes(grant)) notAllowed.push(grant);
    else notHeld.push(grant);
  }
  return { notAllowed, notHeld };
}
