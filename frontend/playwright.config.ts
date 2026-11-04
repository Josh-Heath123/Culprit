import { defineConfig, devices } from "@playwright/test";

/** End-to-end journeys against a running Culprit stack (Phase 32.1):
 * `just quickstart`, then `just e2e`. Nothing here starts a server — the
 * suite tests the compose stack the quickstart built, through Caddy, the
 * way a user reaches it. Environment (just e2e sets all four):
 *
 *   CULPRIT_E2E_BASE_URL       http://localhost, or :$QUICKSTART_HTTP_PORT
 *   CULPRIT_E2E_USERNAME       the quickstart admin
 *   CULPRIT_E2E_PASSWORD
 *   CULPRIT_E2E_PROJECT_TOKEN  to seed the partial investigations
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.CULPRIT_E2E_BASE_URL ?? "http://localhost",
    // No trace: it would record the typed password, the login body and
    // the bearer header. A failure keeps a screenshot (the password field
    // is masked) and the error context.
    trace: "off",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
});
