/**
 * Scenario 10: sqladmin — login page renders, dashboard requires session.
 */
import { test, expect } from "./fixtures";

test("sqladmin login page renders", async ({ request }) => {
  const resp = await request.get("/sqladmin/login");
  expect(resp.ok()).toBeTruthy();
  const html = await resp.text();
  expect(html.toLowerCase()).toContain("html");
});

test("sqladmin dashboard requires admin_session", async ({ request }) => {
  const resp = await request.get("/sqladmin/", {
    maxRedirects: 0,
    failOnStatusCode: false,
  });
  // sqladmin returns 302/303/401 for an anonymous request
  expect([302, 303, 401]).toContain(resp.status());
});
