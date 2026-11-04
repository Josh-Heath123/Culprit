import path from "node:path";

import type { Page } from "@playwright/test";

import { expect, open, state, test } from "./fixtures.ts";

/** Screenshots taken by the suite at fixed widths, so they can only show
 * what works (Phase 32.1): the investigation list, a complete
 * investigation and a partial one, at 375, 768, 1280 and 1920 px.
 * Written to $CULPRIT_E2E_SCREENSHOTS, default frontend/e2e/.screenshots
 * (ignored). Every width is also checked for horizontal overflow — a
 * layout that scrolls sideways at a width has not been adapted to it.
 *
 * One sign-in (sign-in is rate limited); the widths are viewport resizes
 * and the screens are reached by clicking. */

const WIDTHS = [375, 768, 1280, 1920] as const;
const OUT = process.env.CULPRIT_E2E_SCREENSHOTS ?? path.resolve(import.meta.dirname, ".screenshots");

async function atEveryWidth(page: Page, name: string, ready: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId(ready).first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect.soft(overflow, `${name}: horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(OUT, `${name}-${width}.png`), fullPage: true, animations: "disabled" });
  }
}

async function back(page: Page): Promise<void> {
  await page.getByRole("link", { name: "All investigations" }).click();
  await page.waitForURL("**/investigations");
}

test("the investigation screens at 375, 768, 1280 and 1920 px", async ({ page }) => {
  const { complete, partialRefused } = state();
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/investigations");
  await atEveryWidth(page, "list", "investigation-row");

  await page.locator(`a[href="/investigations/${complete}"]`).click();
  await page.waitForURL(`**/investigations/${complete}`);
  await page.getByTestId("edge-toggle").last().click();
  await atEveryWidth(page, "complete", "root-subject");

  await back(page);
  await page.locator(`a[href="/investigations/${partialRefused}"]`).click();
  await page.waitForURL(`**/investigations/${partialRefused}`);
  await atEveryWidth(page, "partial", "stopped-at");
});
