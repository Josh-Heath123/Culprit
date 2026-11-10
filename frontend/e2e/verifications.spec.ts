import { atEveryWidth, expect, open, test } from "./fixtures.ts";

/** Phase 34 part 2: a fix verified through an agent, shown on the
 * investigation's page. The investigation is the one `just agent-e2e`
 * (cli/cmd/culprit/agent_e2e_test.go) diagnosed through an agent in the
 * fault stack, then verified twice through that agent — a wrong fix
 * (not_resolved), then the right one (verified). `just e2e-verified` runs
 * this file after it, naming that investigation; the main journeys run
 * without it, and this test says why it did not run. */
const INVESTIGATION = process.env.CULPRIT_E2E_VERIFIED_INVESTIGATION ?? "";

test("a verified fix: the verifications newest first, and the rubric's verified from the newest", async ({
  page,
}) => {
  test.skip(INVESTIGATION === "", "set by `just e2e-verified`, after `just agent-e2e` has verified an investigation");
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, `/investigations/${INVESTIGATION}`);

  const card = page.getByTestId("verifications");
  const items = card.getByTestId("verification");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toHaveAttribute("data-verdict", "verified");
  await expect(items.nth(0)).toContainText("Newest");
  await expect(items.nth(1)).toHaveAttribute("data-verdict", "not_resolved");
  for (const item of [items.nth(0), items.nth(1)]) {
    await expect(item.getByTestId("verification-changes")).toContainText("config:order-service/INVENTORY_TOKEN");
    await expect(item.getByTestId("verification-source")).toContainText("planted on purpose");
  }
  // The three conditions, each shown, on the verified one.
  for (const clause of ["failing_now_passes", "no_regressions", "changes_explained"]) {
    await expect(items.nth(0).locator(`[data-clause=${clause}]`)).toHaveAttribute("data-holds", "true");
  }
  await expect(items.nth(1).locator("[data-clause=failing_now_passes]")).toHaveAttribute("data-holds", "false");

  // The rubric's fourth criterion is the newest verification's.
  const verified = page.getByTestId("rubric").locator("[data-criterion=verified]");
  await expect(verified).toHaveAttribute("data-holds", "true");
  await expect(verified).toContainText("Verified by the newest verification");

  await atEveryWidth(page, "investigation-verified", () => expect(card).toBeVisible());
});
