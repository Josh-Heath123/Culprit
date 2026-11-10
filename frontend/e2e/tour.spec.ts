import type { Page } from "@playwright/test";

import { atEveryWidth, expect, go, open, state, test as base } from "./fixtures.ts";

/** Every surviving route, one test each: each loads with no console error
 * and no failed request (the fixtures' guard), is checked for horizontal
 * overflow at 375, 768, 1280 and 1920 px, is screenshotted at each width,
 * and is reached by keyboard. The README's screenshots come from this run
 * (docs/screenshots/). Along the way it does what the journeys in field 14
 * name: read investigations, manage settings (create a user, write and
 * delete a postmortem), change password, the command palette, a 404, sign
 * out — and a member meeting an admin page.
 *
 * One test per route, so a broken route fails its own test and no other.
 * Sign-in is rate limited to 10 a minute per address, so the admin's tests
 * share one signed-in page (a worker fixture) and move between routes
 * inside the app, as a user would. When a test fails, Playwright discards
 * the worker; the next test gets a fresh page and signs in again — one
 * more sign-in per failure, never a failure carried into the next route.
 *
 * Screenshots go to $CULPRIT_E2E_SCREENSHOTS, default
 * frontend/e2e/.screenshots (ignored). */

const test = base.extend<object, { adminPage: Page }>({
  adminPage: [
    async ({ browser }, provide, workerInfo) => {
      const context = await browser.newContext({ baseURL: workerInfo.project.use.baseURL });
      const page = await context.newPage();
      await page.setViewportSize({ width: 1280, height: 900 });
      await open(page, "/investigations");
      await provide(page);
      await context.close();
    },
    { scope: "worker" },
  ],
  // Every test in this file runs on the shared, signed-in page, starting
  // at 1280 px with nothing open.
  page: async ({ adminPage }, provide) => {
    await adminPage.setViewportSize({ width: 1280, height: 900 });
    await adminPage.keyboard.press("Escape");
    await provide(adminPage);
  },
});

// The shared page is not the one Playwright screenshots on failure.
test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    await page.screenshot({ path: testInfo.outputPath("failure.png"), fullPage: true }).catch(() => undefined);
  }
});

const DATE = /^\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}, \d{2}:\d{2}$/;
const stamp = () => Date.now().toString(36);

test("investigations: the list", async ({ page }) => {
  await go(page, "/investigations");
  await atEveryWidth(page, "investigations", () => expect(page.getByTestId("investigation-row").first()).toBeVisible());
});

test("investigation: a complete diagnosis, with the four review changes", async ({ page }) => {
  const { complete } = state();
  await go(page, `/investigations/${complete}`);
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
  // The walk's own words: no plan phase, no raw kind, in what it wrote.
  await expect(page.getByTestId("diagnosis")).not.toContainText(/phase \d/i);
  await atEveryWidth(page, "investigation-complete", () => expect(page.getByTestId("root-subject")).toBeVisible());
});

test("investigation: a partial diagnosis", async ({ page }) => {
  const { partialRefused } = state();
  await go(page, `/investigations/${partialRefused}`);
  await expect(page.getByTestId("diagnosis")).not.toContainText(/phase \d/i);
  await atEveryWidth(page, "investigation-partial", () => expect(page.getByTestId("stopped-at")).toBeVisible());
});

test("incidents: the history", async ({ page }) => {
  await go(page, "/incidents");
  await atEveryWidth(page, "incidents", () =>
    expect(page.getByRole("heading", { name: "Incidents", exact: true })).toBeVisible(),
  );
});

test("the command palette", async ({ page }) => {
  await go(page, "/incidents");
  await expect(page.getByRole("heading", { name: "Incidents", exact: true })).toBeVisible();
  await page.keyboard.press("Control+k");
  await atEveryWidth(
    page,
    "command-palette",
    () => expect(page.getByRole("dialog", { name: "Jump to an incident" })).toBeVisible(),
    "[role=dialog]",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("postmortem editor: write one, open it, delete it", async ({ page }) => {
  const title = `E2E postmortem ${stamp()}`;
  await go(page, "/postmortems/new");
  await page.getByLabel("Title").fill(title);
  await atEveryWidth(page, "postmortem-editor", () => expect(page.getByLabel("Title")).toBeVisible());
  await page.getByRole("button", { name: "Create postmortem" }).click();
  await page.waitForURL(/\/postmortems\/[0-9a-f-]{36}$/);
  await atEveryWidth(page, "postmortem-existing", () =>
    expect(page.getByRole("heading", { name: "Edit postmortem", exact: true })).toBeVisible(),
  );
  await page.getByRole("button", { name: "Delete…" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.waitForURL("**/postmortems");
  await expect(page.getByTestId("postmortem-row").filter({ hasText: title })).toHaveCount(0);
});

test("postmortems: the list", async ({ page }) => {
  await go(page, "/postmortems");
  await atEveryWidth(page, "postmortems", () =>
    expect(page.getByRole("heading", { name: "Postmortems", exact: true })).toBeVisible(),
  );
});

test("settings: services", async ({ page }) => {
  await go(page, "/settings/services");
  await atEveryWidth(page, "settings-services", () => expect(page.getByTestId("component-row").first()).toBeVisible());
});

test("settings: users, creating one", async ({ page }) => {
  const id = stamp();
  await go(page, "/settings/users");
  const form = page.getByTestId("add-user-form");
  await form.getByLabel("Username").fill(`e2e-user-${id}`);
  await form.getByLabel("Password").fill(`e2e-password-${id}-long`);
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByTestId("user-row").filter({ hasText: `e2e-user-${id}` })).toBeVisible();
  await atEveryWidth(page, "settings-users", () => expect(page.getByTestId("user-row").first()).toBeVisible());
});

test("change password: the dialog opens, names itself, and cancels", async ({ page }) => {
  await go(page, "/investigations");
  await page.getByRole("button", { name: "Change password" }).click();
  const dialog = page.getByRole("dialog", { name: "Change your password" });
  await atEveryWidth(page, "change-password", () => expect(dialog).toBeVisible(), "[role=dialog]");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});

test("a path that does not exist", async ({ page }) => {
  await go(page, "/no-such-page");
  await atEveryWidth(page, "not-found", () => expect(page.getByTestId("not-found")).toBeVisible());
});

// Signs the shared page out, so it is the admin's last test.
test("sign out, then the sign-in screen", async ({ page }) => {
  await go(page, "/investigations");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await atEveryWidth(page, "sign-in", () =>
    expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible(),
  );
});

// Its own page, signed in as the member global setup created.
base("a member: investigations yes, admin settings no", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/investigations", state().member);
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await go(page, "/settings/users");
  await atEveryWidth(page, "admins-only", () => expect(page.getByTestId("admins-only")).toBeVisible());
});
