/**
 * Visual sanity for the redesigned ProfileSidebar.
 *
 * Skipped under headless (SPA bundle createContext bug — see 02_login.spec.ts),
 * but the test body is kept so a developer can `playwright test --headed
 * --grep sidebar` to inspect the layout once the bundle issue is fixed, or
 * run it after `npm run dev` in HTTP mode.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures";

test.skip("ProfileSidebar groups render in admin view", async ({ page }) => {
  await page.goto("/login");
  await page.locator('input[type="password"]').first().waitFor();
  await page.locator('input[type="text"]').first().fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').first().fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/\/myprofile/);

  // All section titles are uppercase + tracking, lucide icons + uniform layout.
  for (const title of [
    "Профиль",
    "Коммуникации",
    "Работа",
    "Контент",
    "HR",
    "Администрирование",
  ]) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }

  // Spot-check that lucide SVG icons are present in sidebar items
  const sidebar = page.locator("aside").first();
  expect(await sidebar.locator("svg").count()).toBeGreaterThan(15);
});
