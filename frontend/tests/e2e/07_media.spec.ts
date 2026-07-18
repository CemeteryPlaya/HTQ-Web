/**
 * Scenario 9: Media — upload + download + Range request.
 */
import { test, expect } from "./fixtures";

test("upload + download a public file (full body)", async ({
  request,
  adminTokens,
}) => {
  const upload = await request.post("/api/media/v1/files/?is_public=true", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
    multipart: {
      file: {
        name: "e2e.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("hello e2e world"),
      },
    },
  });
  expect(upload.status()).toBe(201);
  const meta = await upload.json();
  expect(meta.id).toBeTruthy();
  expect(meta.url || `/api/media/v1/files/${meta.id}`).toBeTruthy();

  const download = await request.get(`/api/media/v1/files/${meta.id}`);
  expect(download.status()).toBe(200);
  expect(await download.text()).toBe("hello e2e world");
});

test("Range request returns 206 + correct slice", async ({
  request,
  adminTokens,
}) => {
  const upload = await request.post("/api/media/v1/files/?is_public=true", {
    headers: { Authorization: `Bearer ${adminTokens.access}` },
    multipart: {
      file: {
        name: "range.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("0123456789"),
      },
    },
  });
  const meta = await upload.json();

  const ranged = await request.get(`/api/media/v1/files/${meta.id}`, {
    headers: { Range: "bytes=2-5" },
  });
  expect(ranged.status()).toBe(206);
  expect(await ranged.text()).toBe("2345");
  expect(ranged.headers()["content-range"]).toBe("bytes 2-5/10");
});
