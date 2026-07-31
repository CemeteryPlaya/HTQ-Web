import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL || "http://localhost";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: 1,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], headless: true },
    },
    {
      // Бинарника chromium на машинах разработки нет (`npx playwright
      // install` его не тянут), а Edge на Windows стоит всегда — поэтому
      // браузерные спеки гоняются через channel: 'msedge'. Движок тот же
      // Chromium, отдельный проект нужен только чтобы не ставить второй
      // браузер ради того же самого.
      //
      //   npx playwright test 16_ --project=msedge
      name: "msedge",
      use: { ...devices["Desktop Edge"], channel: "msedge", headless: true },
    },
  ],
});
