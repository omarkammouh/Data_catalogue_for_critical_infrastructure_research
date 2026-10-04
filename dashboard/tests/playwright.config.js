// Playwright configuration for the dashboard browser tests.
// Run from dashboard: npx playwright test -c tests/playwright.config.js
const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: /.*\.spec\.js/,
  timeout: 30000,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../test-results",
  use: { browserName: "chromium", headless: true, viewport: { width: 1280, height: 900 } },
});
