/**
 * Scenario 13: Seed sample news + verify the create-through-UI flow.
 *
 *  - Part A seeds four articles (published / scheduled / draft / archived)
 *    straight through the CMS API so the /manage/news board has realistic
 *    data covering every status.
 *  - Part B drives the actual editor dialog once, end to end, and asserts the
 *    article persists and shows up in the public list.
 *
 * Run against the Vite dev server:
 *   E2E_BASE_URL=http://localhost:3001 \
 *   npx playwright test tests/e2e/13_news_seed.spec.ts
 */
import { test, expect } from "@playwright/test";

const EMAIL = process.env.E2E_EDITOR_EMAIL || "qa_superadmin@htq.test";
const PASSWORD = process.env.E2E_EDITOR_PASSWORD || "SuperAdmin!2026";

const STAMP = Date.now();

let access = "";
let refresh = "";

test.beforeEach(async ({ page, request }) => {
  const resp = await request.post("/api/users/v1/token/", {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(resp.ok(), `login as ${EMAIL}`).toBeTruthy();
  const body = await resp.json();
  access = body.access;
  refresh = body.refresh;
  await page.addInitScript(
    ([a, r]) => {
      localStorage.setItem("access", a);
      localStorage.setItem("refresh", r);
    },
    [access, refresh],
  );
});

const RICH_CONTENT = `
<h2>Заголовок раздела</h2>
<p>Это <strong>жирный</strong>, <em>курсивный</em> и <u>подчёркнутый</u> текст,
созданный автотестом для проверки CMS.</p>
<ul><li>Первый пункт</li><li>Второй пункт</li></ul>
<ol><li>Раз</li><li>Два</li></ol>
<blockquote>Цитата для проверки стиля абзаца.</blockquote>
<p>Формула: H<sub>2</sub>O и E = mc<sup>2</sup>.</p>
<hr/>
<p style="text-align:center">Текст по центру.</p>
`.trim();

const SAMPLES = [
  {
    title: `E2E · Опубликованная новость #${STAMP}`,
    slug: `e2e-published-${STAMP}`,
    excerpt: "Готовая к показу новость с форматированным содержимым.",
    status: "published",
    scheduled_at: null as string | null,
  },
  {
    title: `E2E · Запланированная новость #${STAMP}`,
    slug: `e2e-scheduled-${STAMP}`,
    excerpt: "Новость с отложенной публикацией (через сутки).",
    status: "scheduled",
    scheduled_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  },
  {
    title: `E2E · Черновик #${STAMP}`,
    slug: `e2e-draft-${STAMP}`,
    excerpt: "Черновик, который не виден публике.",
    status: "draft",
    scheduled_at: null,
  },
  {
    title: `E2E · Архивная новость #${STAMP}`,
    slug: `e2e-archived-${STAMP}`,
    excerpt: "Архивная запись для проверки фильтра статусов.",
    status: "archived",
    scheduled_at: null,
  },
];

test("seed: create sample news for every status via CMS API", async ({ request }) => {
  const auth = { Authorization: `Bearer ${access}` };
  const created: string[] = [];

  for (const s of SAMPLES) {
    const resp = await request.post("/api/cms/v1/news/", {
      headers: auth,
      data: {
        title: s.title,
        slug: s.slug,
        excerpt: s.excerpt,
        content: RICH_CONTENT,
        status: s.status,
        scheduled_at: s.scheduled_at,
        tag_ids: [],
      },
    });
    expect(
      [200, 201].includes(resp.status()),
      `create ${s.slug} -> ${resp.status()} ${await resp.text()}`,
    ).toBeTruthy();
    const body = await resp.json();
    expect(body.slug).toBe(s.slug);
    expect(body.status).toBe(s.status);
    created.push(s.slug);
  }

  // The published one must be visible to an anonymous reader.
  const pub = await request.get(
    `/api/cms/v1/news/by-slug/e2e-published-${STAMP}`,
  );
  expect(pub.ok()).toBeTruthy();
  const pubBody = await pub.json();
  expect(pubBody.content).toContain("<strong>жирный</strong>");

  console.log(`Seeded news slugs: ${created.join(", ")}`);
});

test("UI: create a news article through the editor dialog", async ({ page }) => {
  const slug = `e2e-ui-${STAMP}`;

  await page.goto("/manage/news");
  await page.getByRole("button", { name: /Новая новость/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 20_000 });

  await page.locator("#news-title").fill(`E2E · Создано через UI #${STAMP}`);
  // Blur the title first: its onBlur auto-generates a slug from the title, and
  // if that fires *during* our slug fill it concatenates with our value. Fill
  // the excerpt (which blurs the title), THEN set the slug deterministically.
  await page
    .locator("#news-excerpt")
    .fill("Новость, созданная автотестом через редактор.");
  await page.locator("#news-slug").fill("");
  await page.locator("#news-slug").fill(slug);
  await expect(page.locator("#news-slug")).toHaveValue(slug);

  // Type into the Jodit surface, then blur so the form picks up the content
  // (NewsEditor commits on blur, not per keystroke).
  const wys = page.locator(".jodit-wysiwyg").first();
  await expect(wys).toBeVisible({ timeout: 15_000 });
  await wys.click();
  await page.keyboard.insertText("Текст новости из E2E-теста.");
  await page.locator("#news-title").click(); // blur the editor

  // Status defaults to "published" — create it.
  await page.getByRole("button", { name: /Создать новость/ }).click();

  // Toast + dialog closes.
  await expect(page.getByText(/Новость создана/)).toBeVisible({ timeout: 10_000 });

  // It now exists via the API.
  const resp = await page.request.get(`/api/cms/v1/news/by-slug/${slug}`);
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.title).toContain("Создано через UI");
});
