/**
 * Scenario 10: the admin panel — login page renders, dashboard requires a session.
 *
 * Was `/sqladmin/*` — the FastAPI admin-service's sqladmin panel, deleted at
 * cutover. The monolith's panel is Django's own at `/django-admin/`
 * (`/admin` stays with the SPA's React pages, see backend/htqweb/urls.py).
 */
import { test, expect } from "./fixtures";

test("django-admin login page renders", async ({ request }) => {
  const resp = await request.get("/django-admin/login/");
  expect(resp.ok()).toBeTruthy();
  const html = await resp.text();
  expect(html.toLowerCase()).toContain("html");
});

test("django-admin dashboard requires a session", async ({ request }) => {
  const resp = await request.get("/django-admin/", {
    maxRedirects: 0,
    failOnStatusCode: false,
  });
  // Django redirects an anonymous request to the login page.
  expect([301, 302]).toContain(resp.status());
  expect(resp.headers()["location"] || "").toContain("/django-admin/login");
});
