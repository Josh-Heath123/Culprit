import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, open, state, test } from "./fixtures.ts";

/** Phase 35 part 2: the narration beside an investigation.
 *
 * CI runs these twice (the e2e job's matrix). With CULPRIT_E2E_NARRATION=stub
 * the worker's `ollama` provider points at scripts/narrator_stub.py,
 * which scripts its replies from a marker in the symptom: a faithful
 * narration, a provider failure carrying secret-looking text, a reply
 * naming things the investigation does not hold, and markup. With `none`,
 * nothing is narrated, the page says narration is off, and the stub — still
 * running — is asked nothing. CULPRIT_E2E_NARRATOR_STUB_URL is where the
 * journeys read the stub's call counts (GET /calls). */
const MODE = process.env.CULPRIT_E2E_NARRATION === "stub" ? "stub" : "none";
const STUB = process.env.CULPRIT_E2E_NARRATOR_STUB_URL ?? "";
const FIXTURES = path.resolve(import.meta.dirname, "../../api/tests/data/investigations");
const SECRETS = ["sk-ant-api03-", "hunter2", "postgresql://narrator"];
const ALLOWED = ["off", "not_narrated", "complete", "failed", "refused"];

type Narration = { state: string; attempts: number; reason?: string | null; named?: string[] | null };

async function calls(): Promise<Record<string, number>> {
  const response = await fetch(`${STUB}/calls`);
  expect(response.ok).toBe(true);
  return (await response.json()) as Record<string, number>;
}

async function token(base: string): Promise<string> {
  const login = await fetch(`${base}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: process.env.CULPRIT_E2E_USERNAME,
      password: process.env.CULPRIT_E2E_PASSWORD,
    }),
  });
  expect(login.ok).toBe(true);
  return ((await login.json()) as { access_token: string }).access_token;
}

/** A copy of the recorded audience investigation, under a fresh id, with
 * the stub's marker in its symptom. Posted with the project token, as CI
 * posts what `culprit diagnose` wrote. */
async function seed(base: string, marker: string): Promise<string> {
  const investigation = JSON.parse(readFileSync(path.join(FIXTURES, "auth-audience.json"), "utf-8")) as {
    id: string;
    symptom: { description: string };
  };
  investigation.id = `inv-${randomBytes(8).toString("hex")}`;
  investigation.symptom.description = `POST /orders answers 500 (${marker})`;
  const response = await fetch(`${base}/api/investigations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.CULPRIT_E2E_PROJECT_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(investigation),
  });
  expect(response.status, await response.text()).toBe(201);
  return investigation.id;
}

/** Reads the narration until `done` holds, failing if any state read on
 * the way is not one of the five — nothing is ever pending. */
async function narrationUntil(
  base: string,
  bearer: string,
  id: string,
  done: (narration: Narration) => boolean,
): Promise<Narration> {
  let last: Narration | undefined;
  await expect
    .poll(
      async () => {
        const response = await fetch(`${base}/api/investigations/${id}/narration`, {
          headers: { Authorization: `Bearer ${bearer}` },
        });
        last = (await response.json()) as Narration;
        expect(ALLOWED).toContain(last.state);
        return done(last);
      },
      { timeout: 120_000, intervals: [1_000, 2_000, 5_000] },
    )
    .toBe(true);
  return last as Narration;
}

test.describe("narration off", () => {
  test.skip(MODE !== "none", "CULPRIT_E2E_NARRATION=none");

  test("the page says narration is off, and no provider is called", async ({ page }) => {
    await open(page, `/investigations/${state().complete}`);
    const card = page.getByTestId("narration");
    await expect(card).toHaveAttribute("data-state", "off");
    await expect(card.getByTestId("narration-off")).toContainText("Narration is off");
    if (STUB) expect((await calls()).total).toBe(0);
  });
});

test.describe("narration with the stub provider", () => {
  test.skip(MODE !== "stub", "CULPRIT_E2E_NARRATION=stub");
  test.describe.configure({ timeout: 240_000 });

  test("a complete narration: derived, with its provider and model, citations as the record's text", async ({
    page,
    baseURL,
  }) => {
    const base = baseURL ?? "";
    const id = await seed(base, "faithful");
    await narrationUntil(base, await token(base), id, (n) => n.state === "complete");

    await open(page, `/investigations/${id}`);
    const card = page.getByTestId("narration");
    await expect(card).toHaveAttribute("data-state", "complete");
    await expect(card.getByTestId("narration-derived")).toHaveText("Derived");
    await expect(card.getByTestId("narration-source")).toContainText("Written by ollama (stub)");
    await expect(card.getByTestId("narration-source")).toContainText("Not a finding");
    // The stub cites [1]: shown as the symptom's evidence text, from the record.
    const first = card.getByTestId("narration-evidence").first();
    await expect(first).toHaveAttribute("data-evidence", "1");
    await expect(first).toContainText("Symptom: http:order-service/POST /orders");
    await expect(card.getByTestId("narration-prose")).not.toContainText("[1]");
  });

  test("a provider failure is shown as failed with a reason, and its secret leaves no trace", async ({
    page,
    baseURL,
  }) => {
    const base = baseURL ?? "";
    const bearer = await token(base);
    const id = await seed(base, "narrator-stub:fail");
    const failed = await narrationUntil(base, bearer, id, (n) => n.state === "failed" && n.attempts === 3);
    expect(failed.reason).toBe("ollama answered HTTP 500");

    // After three attempts, no fourth call: wait past several retry
    // intervals (NARRATOR_RETRY_SECONDS=5 in CI) and count again.
    const after = (await calls())["narrator-stub:fail"];
    await page.waitForTimeout(20_000);
    expect((await calls())["narrator-stub:fail"]).toBe(after);
    expect(after).toBe(3);

    await open(page, `/investigations/${id}`);
    const card = page.getByTestId("narration");
    await expect(card).toHaveAttribute("data-state", "failed");
    await expect(card.getByTestId("narration-failed")).toContainText("ollama answered HTTP 500");
    await expect(card.getByTestId("narration-failed")).toContainText("No further attempt is made");
    const html = await page.content();
    const json = JSON.stringify(failed);
    for (const secret of SECRETS) {
      expect(html).not.toContain(secret);
      expect(json).not.toContain(secret);
    }
  });

  test("a refused narration is shown as refused, with what it named, and not as prose", async ({
    page,
    baseURL,
  }) => {
    const base = baseURL ?? "";
    const id = await seed(base, "narrator-stub:refuse");
    const refused = await narrationUntil(base, await token(base), id, (n) => n.state === "refused");
    // The markdown image is refused for its URL; the names for not being
    // in the investigation (probe.http.reachable is in it, so passes).
    expect(refused.named).toEqual(["a URL", "billing-service"]);

    await open(page, `/investigations/${id}`);
    const card = page.getByTestId("narration");
    await expect(card).toHaveAttribute("data-state", "refused");
    await expect(card.getByTestId("narration-refused")).toContainText("billing-service");
    await expect(card.getByTestId("narration-prose")).toHaveCount(0);
    await expect(card.locator("img")).toHaveCount(0);
    await expect(card).not.toContainText("evil.example");
  });

  test("markdown and HTML in a narration are shown literally", async ({ page, baseURL }) => {
    const base = baseURL ?? "";
    const id = await seed(base, "narrator-stub:markup");
    await narrationUntil(base, await token(base), id, (n) => n.state === "complete");

    await open(page, `/investigations/${id}`);
    const prose = page.getByTestId("narration").getByTestId("narration-prose");
    await expect(prose).toContainText("**Root cause:**");
    await expect(prose).toContainText("<b>see the diagnosis</b>");
    await expect(prose).toContainText("<script>alert(1)</script>");
    await expect(prose.locator("b, strong, script, img, a")).toHaveCount(0);
  });
});
