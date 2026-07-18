/**
 * Scenario 3-4: Profile API — read + update via Bearer token (no UI).
 * (UI-driven editing covered manually; here we lock the API contract.)
 */
import { test, expect } from "./fixtures";

test("GET /profile/me returns shape expected by UI", async ({
  request,
  adminTokens,
}) => {
  const resp = await request.get("/api/users/v1/profile/me", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
  });
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.email).toBeTruthy();
  expect(Array.isArray(body.roles)).toBeTruthy();
});

test("PATCH /profile/me display_name is persisted", async ({
  request,
  adminTokens,
}) => {
  const newName = `E2E ${Date.now()}`;
  const patch = await request.patch("/api/users/v1/profile/me", {
    multipart: { display_name: newName },
    headers: { Authorization: `Bearer ${adminTokens.access}` },
  });
  expect(patch.ok()).toBeTruthy();

  const re = await request.get("/api/users/v1/profile/me", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
  });
  const body = await re.json();
  expect(body.display_name ?? body.displayName).toBe(newName);
});
