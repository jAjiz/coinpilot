import { defineConfig, devices } from "@playwright/test";

// Runs against `vite preview` of a build that already exists (`npm run e2e`
// builds first). The service worker is blocked so that `page.route` sees every
// request; every /api request is answered by the tests, none reaches a platform.
export default defineConfig({
  testDir: "e2e",
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:4173",
    serviceWorkers: "block",
    timezoneId: "Europe/Madrid",
    trace: "retain-on-failure",
  },
  projects: [{ name: "pixel-7", use: { ...devices["Pixel 7"] } }],
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
  },
});
