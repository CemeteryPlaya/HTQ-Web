/**
 * Sanity scenario: SPA shell + the backend answers. Runs first so a broken
 * environment is reported immediately.
 *
 * Before the cutover this file probed eight FastAPI microservices on their own
 * host ports (:8005-:8012). Those services no longer exist — there is one
 * Django backend, so the fan-out collapses to the checks below.
 *
 * Liveness/readiness are spelled differently depending on what the suite is
 * pointed at, so they're tried in both spellings:
 *   • through nginx  — `location = /health` (nginx's own 200) and
 *     `location = /health/ready` (proxied to the service registry);
 *   • straight at the backend (:8000) — `/health/` and `/health/ready/`,
 *     mounted by apps.core (backend/apps/core/urls.py, APPEND_SLASH=False).
 * `/api/core/v1/services/` is the one route that reads identically in both.
 */
import type { APIRequestContext, APIResponse } from "@playwright/test";
import { test, expect } from "./fixtures";

/** First spelling that doesn't 404. Keeps the suite topology-agnostic. */
async function getEither(
  request: APIRequestContext,
  ...paths: string[]
): Promise<APIResponse> {
  let last!: APIResponse;
  for (const p of paths) {
    last = await request.get(p, { failOnStatusCode: false });
    if (last.status() !== 404) return last;
  }
  return last;
}

test("SPA shell loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Hi Tech/i);
  // The React mount point is present
  await expect(page.locator("#root")).toBeAttached();
});

test("liveness endpoint responds 200", async ({ request }) => {
  const resp = await getEither(request, "/health", "/health/");
  expect(resp.status(), "liveness").toBe(200);
  expect((await resp.json()).status).toBe("ok");
});

test("readiness endpoint responds 200", async ({ request }) => {
  // Body shape differs by topology — nginx maps this to the service registry
  // ({services: …}), the backend's own view returns {status: "ok"}. Both mean
  // "the database answered", which is all this check is for.
  const resp = await getEither(request, "/health/ready", "/health/ready/");
  expect(resp.status(), "readiness").toBe(200);
  const body = await resp.json();
  expect(body.status === "ok" || typeof body.services === "object").toBeTruthy();
});

test("service registry lists every domain", async ({ request }) => {
  // GET /api/core/v1/services/ — the on/off registry the SPA reads via
  // hooks/useServiceStatus.ts. Replaces the old per-service health fan-out:
  // one response now covers every domain the platform runs.
  const resp = await request.get("/api/core/v1/services/");
  expect(resp.status()).toBe(200);
  const { services } = await resp.json();
  for (const name of ["users", "hr", "tasks", "approvals", "cms", "media", "mail", "messenger"]) {
    expect(services, `registry entry for ${name}`).toHaveProperty(name);
  }
});
