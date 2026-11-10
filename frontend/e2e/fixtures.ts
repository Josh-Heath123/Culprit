import { readFileSync } from "node:fs";
import path from "node:path";

import { test as base, expect, type ConsoleMessage, type Page, type Request, type Response } from "@playwright/test";

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
      const onConsole = (message: ConsoleMessage) => {
        if (message.type() !== "error") return;
        // The browser's own line for a provoked failure ("Failed to load
        // resource") names the URL only in its location.
        if (message.text().startsWith("Failed to load resource") && expected(message.location().url)) return;
        problems.push(`console: ${message.text()} (${message.location().url})`);
      };
      const onPageError = (error: Error) => problems.push(`page error: ${error.message}`);
      const onRequestFailed = (request: Request) => problems.push(`failed: ${request.method()} ${request.url()}`);
      const onResponse = (response: Response) => {
        if (response.status() >= 400 && !expected(response.url())) {
          problems.push(`HTTP ${response.status()}: ${response.request().method()} ${response.url()}`);
        }
      };
      page.on("console", onConsole);
      page.on("pageerror", onPageError);
      page.on("requestfailed", onRequestFailed);
      page.on("response", onResponse);
      await use();
      // The tour shares one page across its tests, so each test's guard
      // listens only while that test runs.
      page.off("console", onConsole);
      page.off("pageerror", onPageError);
      page.off("requestfailed", onRequestFailed);
      page.off("response", onResponse);
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
export async function open(
  page: Page,
  path: string,
  as: { username: string; password: string } = {
    username: process.env.CULPRIT_E2E_USERNAME ?? "",
    password: process.env.CULPRIT_E2E_PASSWORD ?? "",
  },
): Promise<void> {
  await page.goto(path);
  await page.getByLabel("Username").fill(as.username);
  await page.getByLabel("Password").fill(as.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname === path);
}

/** Moves to a path inside the app without a page load, so the in-memory
 * session survives (a full load would sign out). react-router follows
 * popstate. */
export async function go(page: Page, path: string): Promise<void> {
  await page.evaluate((target) => {
    window.history.pushState({}, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await page.waitForURL((url) => url.pathname === path);
}

// ---- every width, and the keyboard (Phase 32.1; shared since Phase 33 part 3) ----

export const WIDTHS = [375, 768, 1280, 1920] as const;
const OUT = process.env.CULPRIT_E2E_SCREENSHOTS ?? path.resolve(import.meta.dirname, ".screenshots");

export async function atEveryWidth(
  page: Page,
  name: string,
  ready: () => Promise<void>,
  /** Where keyboard focus must land: the page, or an open dialog, which
   * traps focus inside itself. */
  region: "main" | "[role=dialog]" = "main",
): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await ready();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect.soft(overflow, `${name}: horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(OUT, `${name}-${width}.png`), fullPage: true, animations: "disabled" });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await keyboardReaches(page, name, region);
  // AGPL-3.0 section 13 (Phase 33 part 3): every page links to its source.
  const source = page.getByTestId("source-link").getByRole("link", { name: "Source code" });
  await expect.soft(source, `${name}: no link to the source`).toHaveAttribute("href", /^https?:\/\//);
}

/** Keyboard operation, on every route: Tab reaches the page's own content
 * (past the header), or inside an open dialog, within 25 presses, and what
 * has focus draws a visible outline. */
async function keyboardReaches(page: Page, name: string, region: string): Promise<void> {
  if (region === "main") await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (let press = 0; press < 25; press += 1) {
    await page.keyboard.press("Tab");
    const inRegion = await page.evaluate((selector) => {
      const active = document.activeElement;
      return active !== null && active !== document.body && active.closest(selector) !== null;
    }, region);
    if (inRegion) {
      const outline = await page.evaluate(() => {
        const style = getComputedStyle(document.activeElement as Element);
        return style.outlineStyle !== "none" && style.outlineWidth !== "0px";
      });
      expect.soft(outline, `${name}: the focused element shows no focus outline`).toBe(true);
      return;
    }
  }
  expect.soft(false, `${name}: Tab never reached the page content`).toBe(true);
}

