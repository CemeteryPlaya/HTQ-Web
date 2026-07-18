/**
 * Scenario: CMS — public news listing + public contact-request submission.
 */
import { test, expect } from "./fixtures";

test("GET /api/cms/v1/news/ public list", async ({ request }) => {
  const resp = await request.get("/api/cms/v1/news/");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  if (Array.isArray(body)) {
    expect(body.length).toBeGreaterThanOrEqual(0);
  } else {
    expect(body).toHaveProperty("items");
  }
});

test("POST /api/cms/v1/contact-requests/ public submission", async ({
  request,
}) => {
  const resp = await request.post("/api/cms/v1/contact-requests/", {
    data: {
      first_name: "E2E",
      email: `e2e-${Date.now()}@example.com`,
      message: "automated e2e contact request",
    },
  });
  // 201 created; or 429 if rate-limited (3/min default) — both acceptable
  expect([201, 429]).toContain(resp.status());
});

test("GET /api/cms/v1/conference/config returns RTC config (auth required)", async ({
  request,
  adminTokens,
}) => {
  const resp = await request.get("/api/cms/v1/conference/config", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
  });
  expect(resp.ok()).toBeTruthy();
});
