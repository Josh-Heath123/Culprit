import path from "node:path";

import type { Page } from "@playwright/test";

import { expect, go, open, state, test } from "./fixtures.ts";

/** Every surviving route, signed in once, moving as a user would (Phase
 * 32.1 part 2): each one loads with no console error and no failed request
 * (the fixtures' guard), is checked for horizontal overflow at 375, 768,
 * 1280 and 1920 px, and is screenshotted at each width. The README's
 * screenshots come from this run (docs/screenshots/). Along the way it does
 * what the journeys in field 14 name: read investigations, manage settings
 * (create a user, write and delete a postmortem), change password, the
 * command palette, a 404, sign out — and a member meeting an admin page.
 *
 * Screenshots go to $CULPRIT_E2E_SCREENSHOTS, default
 * frontend/e2e/.screenshots (ignored). Sign-in is rate limited to 10 a
 * minute: this test signs in twice (the suite, six times). */

const WIDTHS = [375, 768, 1280, 1920] as const;
const OUT = process.env.CULPRIT_E2E_SCREENSHOTS ?? path.resolve(import.meta.dirname, ".screenshots");

async function atEveryWidth(
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

const DATE = /^\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}, \d{2}:\d{2}$/;

test("every route, as an admin and then a member", async ({ page }) => {
  test.setTimeout(180_000);
  const { complete, partialRefused } = state();
  const stamp = Date.now().toString(36);
  const member = { username: `e2e-member-${stamp}`, password: `e2e-password-${stamp}-long` };

  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/investigations");

  // --- investigations, with the four review changes ---
  await atEveryWidth(page, "investigations", () => expect(page.getByTestId("investigation-row").first()).toBeVisible());
  await page.locator(`a[href="/investigations/${complete}"]`).click();
  await page.waitForURL(`**/investigations/${complete}`);
  await page.getByTestId("edge-toggle").last().click();
  // 1. one date format; 2. the id is not in the header bar
  const opened = page.getByRole("definition").filter({ has: page.locator("time") }).first();
  await expect(opened).toHaveText(DATE);
  await expect(page.locator("header")).not.toContainText(complete);
  // 3. hypotheses read as words, the kind beneath in monospace
  await expect(page.getByTestId("hypothesis-label").filter({ hasText: "Auth audience mismatch" })).toBeVisible();
  await expect(page.getByText("auth_audience_mismatch", { exact: true }).first()).toBeVisible();
  // 4. a flag in prose is code that never breaks
  const flag = page.locator("code", { hasText: "--reference" }).first();
  await expect(flag).toBeVisible();
  await expect(flag).toHaveCSS("white-space", "nowrap");
  await atEveryWidth(page, "investigation-complete", () => expect(page.getByTestId("root-subject")).toBeVisible());

  await page.getByRole("link", { name: "All investigations" }).click();
  await page.locator(`a[href="/investigations/${partialRefused}"]`).click();
  await atEveryWidth(page, "investigation-partial", () => expect(page.getByTestId("stopped-at")).toBeVisible());

  // --- incidents (history) and the command palette ---
  await page.getByRole("link", { name: /Incidents/ }).first().click();
  await page.waitForURL((url) => url.pathname === "/incidents");
  await expect(page.getByRole("heading", { name: "Incidents", exact: true })).toBeVisible();
  await page.keyboard.press("Control+k");
  await atEveryWidth(page, "command-palette", () =>
    expect(page.getByRole("dialog", { name: "Jump to an incident" })).toBeVisible(),
    "[role=dialog]",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await atEveryWidth(page, "incidents", () => expect(page.getByRole("heading", { name: "Incidents", exact: true })).toBeVisible());

  // --- postmortems: write one, see it listed, delete it ---
  await page.getByRole("link", { name: "Postmortems" }).first().click();
  await page.waitForURL("**/postmortems");
  await page.getByRole("link", { name: "Write a postmortem" }).click();
  await page.waitForURL("**/postmortems/new");
  await page.getByLabel("Title").fill(`E2E postmortem ${stamp}`);
  await atEveryWidth(page, "postmortem-editor", () => expect(page.getByLabel("Title")).toBeVisible());
  await page.getByRole("button", { name: "Create postmortem" }).click();
  await page.waitForURL(/\/postmortems\/[0-9a-f-]{36}$/);
  await atEveryWidth(page, "postmortem-existing", () =>
    expect(page.getByRole("heading", { name: "Edit postmortem", exact: true })).toBeVisible(),
  );
  await page.getByRole("link", { name: "Postmortems" }).first().click();
  await expect(page.getByTestId("postmortem-row").filter({ hasText: `E2E postmortem ${stamp}` })).toBeVisible();
  await atEveryWidth(page, "postmortems", () => expect(page.getByTestId("postmortem-row").first()).toBeVisible());
  await page.getByTestId("postmortem-row").filter({ hasText: `E2E postmortem ${stamp}` }).click();
  await page.getByRole("button", { name: "Delete…" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.waitForURL("**/postmortems");
  await expect(page.getByTestId("postmortem-row").filter({ hasText: `E2E postmortem ${stamp}` })).toHaveCount(0);

  // --- settings: services, users (create a member) ---
  await page.getByRole("link", { name: "Services" }).first().click();
  await page.waitForURL("**/settings/services");
  await expect(page.getByTestId("component-row").first()).toBeVisible();
  await atEveryWidth(page, "settings-services", () => expect(page.getByTestId("component-row").first()).toBeVisible());

  await page.getByRole("link", { name: "Users" }).first().click();
  await page.waitForURL("**/settings/users");
  const form = page.getByTestId("add-user-form");
  await form.getByLabel("Username").fill(member.username);
  await form.getByLabel("Password").fill(member.password);
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByTestId("user-row").filter({ hasText: member.username })).toBeVisible();
  await atEveryWidth(page, "settings-users", () => expect(page.getByTestId("user-row").first()).toBeVisible());

  // --- change password: the dialog opens, names itself, and cancels ---
  await page.getByRole("button", { name: "Change password" }).click();
  const dialog = page.getByRole("dialog", { name: "Change your password" });
  await atEveryWidth(page, "change-password", () => expect(dialog).toBeVisible(), "[role=dialog]");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);

  // --- a path that does not exist ---
  await go(page, "/no-such-page");
  await atEveryWidth(page, "not-found", () => expect(page.getByTestId("not-found")).toBeVisible());

  // --- sign out, then the sign-in screen itself ---
  await go(page, "/investigations");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await atEveryWidth(page, "sign-in", () => expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible());

  // --- a member: investigations yes, admin settings no ---
  await open(page, "/investigations", member);
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await go(page, "/settings/users");
  await atEveryWidth(page, "admins-only", () => expect(page.getByTestId("admins-only")).toBeVisible());
});
