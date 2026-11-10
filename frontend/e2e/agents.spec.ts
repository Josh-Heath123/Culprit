import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import type { Request } from "@playwright/test";

import { atEveryWidth, expect, go, open, state, test } from "./fixtures.ts";

/** Phase 33 part 3: every action on the agents screen, and opening an
 * investigation through an agent, with a real agent — the shipped Compose
 * recipe (deploy/agent/compose.yaml), paired with a code made here in the
 * browser, reaching this quickstart only through its published address.
 *
 * The agent is driven by scripts/agent_recipe.sh. CI runs it with bash, from
 * the repository; a local run can point CULPRIT_E2E_AGENT_RECIPE at another
 * way in (e.g. `wsl.exe -d Ubuntu-22.04 -e bash /mnt/c/.../agent_recipe.sh`)
 * and CULPRIT_E2E_AGENT_WORK at a directory that side can write. */

const RECIPE = (
  process.env.CULPRIT_E2E_AGENT_RECIPE ?? `bash ${path.resolve(import.meta.dirname, "../../scripts/agent_recipe.sh")}`
).split(" ");

function recipe(command: string, work: string, extra: string[] = [], input?: string): string {
  const [program, ...args] = RECIPE;
  return execFileSync(program, [...args, command, work, ...extra], {
    input,
    encoding: "utf-8",
    stdio: ["pipe", "pipe", "pipe"],
    timeout: 240_000,
  });
}

const SYMPTOM = "POST http://order-service:8001/orders";
const ENVIRONMENT = "quickstart";

test("agents: pair a real agent, allow it, investigate through it, revoke it", async ({ page }) => {
  test.setTimeout(600_000);
  const id = `e2e-agent-${Date.now().toString(36)}`;
  const work = process.env.CULPRIT_E2E_AGENT_WORK
    ? `${process.env.CULPRIT_E2E_AGENT_WORK}/${id}`
    : mkdtempSync(path.join(tmpdir(), "culprit-agent-"));

  // Every request the page makes to start a task, so "starts nothing" is
  // something this test can see.
  const taskRequests: string[] = [];
  page.on("request", (request: Request) => {
    if (request.method() === "POST" && /\/agents\/[^/]+\/tasks$/.test(new URL(request.url()).pathname)) {
      taskRequests.push(request.url());
    }
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/settings/agents");

  try {
    await test.step("a pairing code, shown once", async () => {
      await page.getByRole("button", { name: "Create a pairing code" }).click();
      const dialog = page.getByRole("dialog", { name: "Pairing code" });
      await expect(dialog.getByTestId("pairing-code")).toHaveText(/\S{8,}/);
      const code = (await dialog.getByTestId("pairing-code").textContent())!.trim();
      await atEveryWidth(page, "agents-pairing-code", () => expect(dialog).toBeVisible(), "[role=dialog]");
      await dialog.getByRole("button", { name: "Done" }).click();
      await expect(dialog).toHaveCount(0);

      // The real agent: the Compose recipe, its key written by the agent's
      // own user, the code spent from standard input.
      recipe("compose-prepare", work, [id]);
      recipe("compose-pair", work, [], `${code}\n`);
      recipe("compose-up", work);
    });

    const row = page.locator(`[data-testid=agent-row][data-agent="${id}"]`);

    await test.step("the paired agent appears, and makes signed requests", async () => {
      await expect(row).toBeVisible({ timeout: 30_000 });
      await expect(row.getByTestId("agent-status")).toHaveText("paired");
      await expect(row.getByTestId("agent-last-request")).toContainText("Last signed request", { timeout: 30_000 });
      // A new agent is allowed nothing.
      const grants = row.locator(`[data-testid=agent-grants][data-environment=${ENVIRONMENT}]`);
      await expect(grants.getByText("not allowed").first()).toBeVisible();
      await expect(grants.getByText("allowed", { exact: true })).toHaveCount(0);
    });

    await test.step("with nothing allowed, the dashboard explains why and starts nothing", async () => {
      await go(page, "/investigations");
      const control = page.getByTestId("investigate-through-agent");
      await control.getByLabel("Agent").selectOption(id);
      await control.getByLabel("Environment").selectOption(ENVIRONMENT);
      await control.getByLabel("Symptom").fill(SYMPTOM);
      const why = control.getByTestId("investigate-unavailable");
      await expect(why).toContainText("net.tcp.connect");
      await expect(why).toContainText("net.http.outbound");
      await expect(why).toContainText("Allow it under Settings → Agents");
      await expect(why).toContainText("Nothing has been started.");
      await atEveryWidth(page, "investigate-unavailable", () => expect(why).toBeVisible());
      const start = control.getByRole("button", { name: "Start the investigation" });
      await expect(start).toBeDisabled();
      await control.getByLabel("Symptom").press("Enter");
      await page.waitForTimeout(500);
      expect(taskRequests, "a task was addressed though the agent may not use what it needs").toEqual([]);
    });

    await test.step("change the allowance: the diff, then save", async () => {
      await go(page, "/settings/agents");
      await row.getByRole("button", { name: "Edit allowance" }).click();
      const dialog = page.getByRole("dialog", { name: new RegExp(`Allowance for ${id}`) });
      await dialog.getByRole("checkbox", { name: /Open a TCP connection/ }).check();
      await dialog.getByRole("checkbox", { name: /Send read-only HTTP requests/ }).check();
      const diff = dialog.getByTestId("allowance-diff");
      await expect(diff.locator("[data-change=added]")).toHaveCount(2);
      await expect(diff).toContainText("+ net.http.outbound");
      await expect(diff).toContainText("+ net.tcp.connect");
      await expect(diff.locator("[data-change=removed]")).toHaveCount(0);
      await atEveryWidth(page, "agents-allowance", () => expect(dialog).toBeVisible(), "[role=dialog]");
      await dialog.getByRole("button", { name: "Save allowance" }).click();
      await expect(dialog).toHaveCount(0);
      const grants = row.locator(`[data-testid=agent-grants][data-environment=${ENVIRONMENT}]`);
      await expect(grants.getByText("allowed", { exact: true })).toHaveCount(2);
    });

    await test.step("open an investigation from the dashboard, through the agent", async () => {
      await go(page, "/investigations");
      const control = page.getByTestId("investigate-through-agent");
      await control.getByLabel("Agent").selectOption(id);
      await control.getByLabel("Environment").selectOption(ENVIRONMENT);
      await control.getByLabel("Symptom").fill(SYMPTOM);
      await expect(control.getByTestId("investigate-unavailable")).toHaveCount(0);
      await control.getByRole("button", { name: "Start the investigation" }).click();
      await expect(control.getByTestId("investigate-progress")).toBeVisible();
      await page.waitForURL(/\/investigations\/inv-[0-9a-f]+$/, { timeout: 180_000 });
      await expect(page.getByTestId("diagnosis")).toBeVisible();
      expect(taskRequests).toHaveLength(1);
    });

    await test.step("the agents screen, at every width", async () => {
      await go(page, "/settings/agents");
      await atEveryWidth(page, "settings-agents", () => expect(row).toBeVisible());
    });

    await test.step("revoke: confirm, and the agent's next request is refused", async () => {
      await row.getByRole("button", { name: "Revoke" }).click();
      const dialog = page.getByRole("dialog", { name: new RegExp(`Revoke ${id}`) });
      await expect(dialog).toContainText("cannot be undone");
      await dialog.getByRole("button", { name: "Revoke agent" }).click();
      await expect(row.getByTestId("agent-status")).toHaveText("revoked");
      await expect(row.getByRole("button", { name: "Edit allowance" })).toHaveCount(0);
      // The agent polls every two seconds; its next claim is refused, and it
      // says so on its way out.
      await expect
        .poll(() => recipe("compose-logs", work), { timeout: 60_000, intervals: [2_000] })
        .toMatch(/tasks\/claim: the control plane answered 401/);
    });
  } finally {
    try {
      recipe("compose-down", work);
    } catch {
      // Best effort: the run's result is what the steps above said.
    }
  }
});

// Its own page, signed in as the member global setup created.
test("a member: no agents screen, and no control that starts an investigation", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/investigations", state().member);
  await expect(page.getByTestId("investigate-through-agent")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Agents" })).toHaveCount(0);
  await go(page, "/settings/agents");
  await expect(page.getByTestId("admins-only")).toContainText("This page is for admins");
});
