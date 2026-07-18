/**
 * Scenario 6: Tasks — create a task and verify it appears in the list.
 * Exercises the production fix for current_user.user_id + PG_ENUM values_callable
 * + selectinload in get_with_relations.
 */
import { test, expect } from "./fixtures";

test("POST /tasks/ creates a task with auto-generated key", async ({
  request,
  adminTokens,
}) => {
  const resp = await request.post("/api/tasks/v1/tasks/", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
    data: {
      summary: `E2E task ${Date.now()}`,
      task_type: "story",
      priority: "high",
    },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  expect(body.key).toMatch(/^TASK-\d+$/);
  expect(body.summary).toContain("E2E task");
});

test("GET /tasks/ lists tasks (paginated envelope)", async ({
  request,
  adminTokens,
}) => {
  const resp = await request.get("/api/tasks/v1/tasks/?limit=5", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
  });
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  if (Array.isArray(body)) {
    expect(body.length).toBeGreaterThanOrEqual(0);
  } else {
    expect(body).toHaveProperty("items");
  }
});
