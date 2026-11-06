import type { Page } from "@playwright/test";

import { expect, open, state, test } from "./fixtures.ts";

const AUDIENCE = "auth:order-service->inventory-service/audience";

async function openFromList(page: Page, id: string): Promise<void> {
  if (!page.url().endsWith("/investigations")) {
    await page.getByRole("link", { name: "All investigations" }).click();
    await page.waitForURL("**/investigations");
  }
  await page.locator(`a[href="/investigations/${id}"]`).click();
  await page.waitForURL(`**/investigations/${id}`);
}

/** Phase 32 part 2's browser check, committed as the first journey
 * (Phase 32.1, carried in), followed by the partial ones. One sign-in:
 * the rest is clicking, as a user would.
 *
 * Complete: the root marked once and equal to the injected fault, the
 * rubric as four booleans, the attestation, every edge expanded to its
 * readings, all four hypothesis groups.
 *
 * Partial (Phase 32.1 field 14): where the walk stopped and what it could
 * not check — never under the word "root" or "cause", in the list or the
 * view, and no fix suggested. */
test("reading investigations: one complete, three partial", async ({ page }) => {
  const { complete, partialRefused, partialNothingFailed, partialBoundary } = state();
  const partials = [partialRefused, partialNothingFailed, partialBoundary];
  await open(page, "/investigations");

  // --- the list ---
  const completeRow = page.locator(`a[href="/investigations/${complete}"]`);
  await expect(completeRow.getByTestId("row-root")).toContainText(AUDIENCE);
  for (const id of partials) {
    const row = page.locator(`a[href="/investigations/${id}"]`);
    await expect(row.getByTestId("row-stopped")).toContainText("Walk stopped at");
    await expect(row.getByTestId("row-root")).toHaveCount(0);
    await expect(row).not.toContainText(/\broot\b|\bcause\b/i);
  }

  // --- the complete one ---
  await openFromList(page, complete);
  await expect(page.getByTestId("root-subject")).toHaveText(AUDIENCE);
  await expect(page.getByTestId("root-marker")).toHaveCount(1);
  await expect(page.locator("li", { has: page.getByTestId("root-marker") }).first()).toContainText(AUDIENCE);
  const rubric = page.getByTestId("rubric");
  for (const [criterion, holds] of [
    ["reproduced", "true"],
    ["discriminated", "true"],
    ["counterfactual", "false"],
    ["verified", "false"],
  ]) {
    await expect(rubric.locator(`[data-criterion="${criterion}"]`)).toHaveAttribute("data-holds", holds);
  }
  await expect(page.getByTestId("attestation")).toContainText("reported");
  await expect(page.getByTestId("edge-readings")).toHaveCount(0);
  const toggles = page.getByTestId("edge-toggle");
  await expect(toggles.first()).toHaveAttribute("aria-expanded", "false");
  const count = await toggles.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) await toggles.nth(index).click();
  await expect(page.getByTestId("edge-readings")).toHaveCount(count);
  await expect(
    page
      .getByTestId("edge-readings")
      .filter({ hasText: "probe.auth.token_shape" })
      .locator('[data-verdict="fail"]')
      .first(),
  ).toBeVisible();
  for (const group of ["supported", "ruled_out", "unexplored", "untested"]) {
    await expect(page.getByTestId(`hypotheses-${group}`)).toBeVisible();
  }
  await expect(page.getByTestId("stopped-at")).toHaveCount(0);

  // --- the three partial ones: nothing on the page says root or cause,
  // the fault tree included ---
  for (const id of partials) {
    await openFromList(page, id);
    const diagnosis = page.getByTestId("diagnosis");
    await expect(diagnosis).toContainText("partial");
    await expect(page.getByTestId("stopped-at")).toBeVisible();
    await expect(page.getByTestId("could-not-check")).toBeVisible();
    await expect(diagnosis).not.toContainText(/\broot\b|\bcause\b|suggested fix/i);
    await expect(page.getByTestId("root-marker")).toHaveCount(0);
    await expect(page.getByTestId("root-subject")).toHaveCount(0);
    const toggles = page.getByTestId("edge-toggle");
    for (let index = 0; index < (await toggles.count()); index += 1) await toggles.nth(index).click();
    await expect(page.locator("main")).not.toContainText(/root|cause|caused by/i);
  }

  // Its boundary edge is where the walk stopped, and it is still shown.
  await openFromList(page, partialBoundary);
  await expect(page.getByTestId("stopped-marker")).toHaveCount(1);
  await expect(page.getByTestId("edge-toggle").filter({ hasText: "walk stopped at" })).toHaveCount(1);

  // The refused hypothesis is what the walk could not check, with why.
  await openFromList(page, partialRefused);
  const unchecked = page.getByTestId("could-not-check");
  await expect(unchecked).toContainText(AUDIENCE);
  await expect(unchecked).toContainText("config.inspect.values");
});

/** The main journey by keyboard alone (field 14): sign in, choose the
 * investigation, expand an edge. */
test("the main journey works by keyboard alone", async ({ page }) => {
  const { complete } = state();
  await page.goto("/investigations");
  // The sign-in form focuses the username field itself; type only once it
  // has, or the first keystrokes go nowhere.
  await expect(page.getByLabel("Username")).toBeFocused();
  await page.keyboard.type(process.env.CULPRIT_E2E_USERNAME ?? "");
  await page.keyboard.press("Tab");
  await page.keyboard.type(process.env.CULPRIT_E2E_PASSWORD ?? "");
  await page.keyboard.press("Enter");
  await page.waitForURL("**/investigations");
  await expect(page.locator(`a[href="/investigations/${complete}"]`)).toBeVisible();

  const tabUntil = async (predicate: () => Promise<boolean>) => {
    for (let step = 0; step < 60; step += 1) {
      await page.keyboard.press("Tab");
      if (await predicate()) return;
    }
    throw new Error("never reached by Tab");
  };
  await tabUntil(() =>
    page.evaluate((href) => document.activeElement?.getAttribute("href") === href, `/investigations/${complete}`),
  );
  await page.keyboard.press("Enter");
  await page.waitForURL(`**/investigations/${complete}`);

  await tabUntil(() =>
    page.evaluate(() => document.activeElement?.getAttribute("data-testid") === "edge-toggle"),
  );
  const focused = page.locator(":focus");
  await expect(focused).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Enter");
  await expect(focused).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("edge-readings").first()).toBeVisible();
});

test.describe("a deliberate error path", () => {
  test.use({ expectedFailures: [/\/api\/investigations\/inv-does-not-exist\/tree$/] });

  test("an investigation that does not exist says so, and offers no retry", async ({ page }) => {
    await open(page, "/investigations/inv-does-not-exist");
    const error = page.getByTestId("error-state");
    await expect(error).toContainText("No investigation with this id is stored.");
    // A retry cannot make it exist, so none is offered.
    await expect(error.getByRole("button")).toHaveCount(0);
  });
});
