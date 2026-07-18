import { test as base, request } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || "admin@htqweb.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "admin123";
const API_BASE = process.env.E2E_API_BASE || "http://localhost";

export type Tokens = { access: string; refresh: string };

export async function loginAs(
  email: string,
  password: string,
): Promise<Tokens> {
  const ctx = await request.newContext({ baseURL: API_BASE });
  const resp = await ctx.post("/api/users/v1/token/", {
    data: { email, password },
  });
  if (!resp.ok()) {
    throw new Error(`login failed: ${resp.status()} ${await resp.text()}`);
  }
  const json = await resp.json();
  await ctx.dispose();
  return { access: json.access, refresh: json.refresh };
}

type Fixtures = {
  adminTokens: Tokens;
};

export const test = base.extend<Fixtures>({
  adminTokens: async ({}, use) => {
    const tokens = await loginAs(ADMIN_EMAIL, ADMIN_PASSWORD);
    await use(tokens);
  },
});

export { expect } from "@playwright/test";
export { ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE };
