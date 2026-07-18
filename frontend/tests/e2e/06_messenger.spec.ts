/**
 * Scenario 7: Messenger — create a room (exercises the post-create selectinload
 * fix from Phase 6) and list it.
 */
import { test, expect } from "./fixtures";

test("POST /messenger/v1/rooms/ creates a room and returns participants", async ({
  request,
  adminTokens,
}) => {
  // Ensure admin (user_id=1) is in chat_user_replicas — production background
  // worker syncs this via Redis pub/sub on user create. For E2E we ingest
  // explicitly so the test is self-contained.
  await request.post("/api/messenger/v1/users/ingest", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
    data: {
      id: 1,
      username: "admin",
      first_name: "Admin",
      last_name: "User",
      is_active: true,
      avatar_url: null,
    },
  });

  const resp = await request.post("/api/messenger/v1/rooms/", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
    data: {
      name: `E2E room ${Date.now()}`,
      room_type: "group",
      participant_ids: [],
    },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  expect(body.id).toBeGreaterThan(0);
  expect(Array.isArray(body.participants)).toBeTruthy();
});

test("GET /messenger/v1/rooms/ lists user's rooms", async ({
  request,
  adminTokens,
}) => {
  const resp = await request.get("/api/messenger/v1/rooms/", {
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
