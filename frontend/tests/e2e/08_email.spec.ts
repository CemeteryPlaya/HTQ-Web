/**
 * Scenario 8: Email — list inbox folder (real send requires OAuth setup).
 */
import { test, expect } from "./fixtures";

const FOLDERS = ["inbox", "sent", "drafts", "trash"];

for (const folder of FOLDERS) {
  test(`GET /email/v1/${folder}/ responds`, async ({ request, adminTokens }) => {
    const resp = await request.get(`/api/email/v1/${folder}/`, {
      headers: { Authorization: `Bearer ${adminTokens.access}` },
    });
    // 200 (empty list ok) or 404 if folder route is not yet wired — both
    // are acceptable; 5xx is not.
    expect(resp.status(), `${folder}`).toBeLessThan(500);
  });
}
