import { defineConfig } from "@playwright/test";

// Requires the local stack (`make dev`) and demo seed (`make seed`).
// Uses the installed Google Chrome (channel "chrome") so no browser download is needed;
// set PW_CHANNEL= to use Playwright's bundled Chromium instead (`npx playwright install chromium`).
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3400",
    channel: process.env.PW_CHANNEL ?? "chrome",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
