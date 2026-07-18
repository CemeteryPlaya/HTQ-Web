/**
 * Sanity scenario: SPA shell + every backend /health/ responds.
 * Runs first so a broken environment is reported immediately.
 */
import { test, expect, API_BASE } from "./fixtures";

test("SPA shell loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Hi Tech/i);
  // The React mount point is present
  await expect(page.locator("#root")).toBeAttached();
});

const SERVICES = [
  ["user", 8005],
  ["hr", 8006],
  ["task", 8007],
  ["messenger", 8008],
  ["media", 8009],
  ["email", 8010],
  ["cms", 8011],
  ["admin", 8012],
] as const;

for (const [name, port] of SERVICES) {
  test(`${name}-service /health/ responds 200`, async ({ request }) => {
    const resp = await request.get(`http://localhost:${port}/health/`);
    expect(resp.status(), `${name}-service health`).toBe(200);
  });
}
