/**
 * Scenario 5: HR — list endpoints respond. (Create flow needs richer fixtures
 *  and is covered by services/hr integration tests.)
 */
import { test, expect } from "./fixtures";

const ENDPOINTS = [
  "/api/hr/v1/employees/",
  "/api/hr/v1/departments/",
  "/api/hr/v1/positions/",
  "/api/hr/v1/personnel-history/",
  "/api/hr/v1/logs/",
];

for (const url of ENDPOINTS) {
  test(`HR ${url} responds with an array or paginated envelope`, async ({
    request,
    adminTokens,
  }) => {
    const resp = await request.get(url, {
      headers: { Authorization: `Bearer ${adminTokens.access}` },
    });
    expect(resp.status(), `${url} status`).toBe(200);
    const body = await resp.json();
    if (Array.isArray(body)) return;
    expect(body).toHaveProperty("items");
    expect(Array.isArray(body.items)).toBeTruthy();
  });
}
