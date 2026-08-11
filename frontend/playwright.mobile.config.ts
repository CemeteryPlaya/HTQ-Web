import { defineConfig } from '@playwright/test';

/**
 * Отдельный конфиг под мобильный UI/UX-аудит.
 *
 * Не вливается в `playwright.config.ts`, потому что тот ходит на nginx
 * (`http://localhost`, профиль production), а этому набору нужен Vite с его
 * прокси — и свой `webServer`, чтобы набор запускался одной командой.
 *
 * Браузер везде `msedge`: бинарника chromium на машинах разработки нет, а
 * движок тот же самый. `isMobile`/`hasTouch` включены — без них не работают
 * тач-обработчики каруселей и медиазапросы hover.
 */
const baseURL = process.env.E2E_MOBILE_BASE_URL || 'http://localhost:3000';

const mobileUse = {
  channel: 'msedge' as const,
  headless: true,
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 3,
};

export default defineConfig({
  testDir: './tests/e2e-mobile',
  fullyParallel: false,
  workers: 1,
  // Половина проверок зависит от лэйаута после подгрузки данных — одна
  // повторная попытка отсекает мигания сети, но не маскирует стабильный баг.
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-mobile' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      // Самый узкий реально встречающийся Android — здесь вёрстка рвётся первой.
      name: 'android-360',
      use: { ...mobileUse, viewport: { width: 360, height: 740 } },
    },
    {
      // iPhone 12/13/14/15 — самый массовый размер экрана.
      name: 'iphone-390',
      use: { ...mobileUse, viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
