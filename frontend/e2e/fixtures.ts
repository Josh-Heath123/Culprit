import { readFileSync } from "node:fs";

import { test as base, expect, type Page } from "@playwright/test";

import { STATE, type E2EState } from "./global-setup.ts";

/** Every test fails on a console error or a failed request on its
 * success path (Phase 31.2's criterion 4, refined 2026-11-04). A test of
 * a deliberate error path lists the requests it provokes in
 * `expectedFailures`; anything else still fails it. */
export const test = base.extend<{ expectedFailures: RegExp[]; guard: void }>({
  expectedFailures: [[], { option: true }],
  guard: [
    async ({ page, expectedFailures }, use) => {
      const problems: string[] = [];
      const expected = (url: string) => expectedFailures.some((pattern) => pattern.test(url));
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        // The browser's own line for a provoked failure ("Failed to load
        // resource") names the URL only in its location.
        if (message.text().startsWith("Failed to load resource") && expected(message.location().url)) return;
        problems.push(`console: ${message.text()} (${message.location().url})`);
      });
      page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
      page.on("requestfailed", (request) => problems.push(`failed: ${request.method()} ${request.url()}`));
      page.on("response", (response) => {
        if (response.status() >= 400 && !expected(response.url())) {
          problems.push(`HTTP ${response.status()}: ${response.request().method()} ${response.url()}`);
        }
      });
      await use();
      expect(problems, "console errors or failed requests").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export function state(): E2EState {
  return JSON.parse(readFileSync(STATE, "utf-8")) as E2EState;
}

/** The session token lives in memory only (lib/auth.ts), so every full
 * page load signs in again. Opening a protected path redirects to
 * /login?next=…, and signing in lands back on it. Sign-in is limited to
 * 10 a minute per address (api/app/auth/router.py), so a test signs in
 * once and then moves by clicking, as a user would. */
export async function open(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.getByLabel("Username").fill(process.env.CULPRIT_E2E_USERNAME ?? "");
  await page.getByLabel("Password").fill(process.env.CULPRIT_E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname === path);
}
