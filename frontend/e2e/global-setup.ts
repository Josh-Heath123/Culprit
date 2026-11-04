import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

/** Seeds what the quickstart does not produce, and records which
 * investigation is which for the specs.
 *
 * The quickstart posts one complete investigation (the audience fault).
 * The partial ones are posted here, from the investigations the fault
 * library recorded from real walks (api/tests/data/investigations/,
 * synthetic demo data only — field 12). A 409 means an earlier run already
 * stored it: investigations are append-only, so that is success. */

const FIXTURES = path.resolve(import.meta.dirname, "../../api/tests/data/investigations");
export const STATE = path.resolve(import.meta.dirname, ".state.json");

export interface E2EState {
  complete: string;
  partialRefused: string;
  partialNothingFailed: string;
  partialBoundary: string;
}

function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set — run the suite with \`just e2e\` (frontend/playwright.config.ts)`);
  return value;
}

async function post(base: string, token: string, file: string): Promise<string> {
  const body = readFileSync(path.join(FIXTURES, file), "utf-8");
  const response = await fetch(`${base}/api/investigations`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body,
  });
  if (response.status !== 201 && response.status !== 409) {
    throw new Error(`POST ${file}: ${response.status} ${await response.text()}`);
  }
  return (JSON.parse(body) as { id: string }).id;
}

export default async function globalSetup(): Promise<void> {
  const base = process.env.CULPRIT_E2E_BASE_URL ?? "http://localhost";
  const projectToken = env("CULPRIT_E2E_PROJECT_TOKEN");
  const partialRefused = await post(base, projectToken, "auth-audience-ungranted.json");
  const partialNothingFailed = await post(base, projectToken, "latency.json");
  // The one partial investigation with a fault tree: recorded from the walk
  // in cli/internal/isolate's TestABoundaryWithUntestedAlternatives… (no
  // fault-library case produces one).
  const partialBoundary = await post(base, projectToken, "partial-with-boundary.json");

  const login = await fetch(`${base}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: env("CULPRIT_E2E_USERNAME"), password: env("CULPRIT_E2E_PASSWORD") }),
  });
  if (!login.ok) throw new Error(`login: ${login.status}`);
  const { access_token } = (await login.json()) as { access_token: string };
  const list = await fetch(`${base}/api/investigations?limit=200`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  const { items } = (await list.json()) as {
    items: { id: string; root_subject: string | null; complete: boolean | null; opened_at: string }[];
  };
  const complete = items.find(
    (item) => item.complete === true && item.root_subject === "auth:order-service->inventory-service/audience",
  );
  if (!complete) throw new Error("no complete audience investigation is stored — run `just quickstart` first");

  mkdirSync(path.dirname(STATE), { recursive: true });
  const state: E2EState = { complete: complete.id, partialRefused, partialNothingFailed, partialBoundary };
  writeFileSync(STATE, JSON.stringify(state, null, 2));
}
