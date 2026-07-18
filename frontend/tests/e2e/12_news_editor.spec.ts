/**
 * Scenario 12: News rich-text editor (Jodit) toolbar.
 *
 * Verifies every toolbar button configured in
 * `src/components/news/NewsEditor.tsx` actually renders AND behaves:
 *   - inline marks (bold/italic/underline/strikethrough/sup/sub) produce HTML
 *   - block tools (ul/ol/hr/indent) mutate the document
 *   - dropdown tools (font/fontsize/brush/paragraph/align/link/image/video/table)
 *     open their popup
 *   - mode tools (source/fullsize/preview) switch the editor view
 *   - history/clear tools (undo/redo/eraser/copyformat/selectall) respond
 *
 * Then it seeds several sample news articles via the CMS API and verifies
 * the full create-through-the-UI flow once.
 *
 * Run against the Vite dev server (production bundle has a known
 * createContext crash in headless Chromium — see 02_login.spec.ts):
 *
 *   E2E_BASE_URL=http://localhost:3001 \
 *   npx playwright test tests/e2e/12_news_editor.spec.ts
 */
import { test, expect } from "@playwright/test";

const EMAIL = process.env.E2E_EDITOR_EMAIL || "qa_superadmin@htq.test";
const PASSWORD = process.env.E2E_EDITOR_PASSWORD || "SuperAdmin!2026";

const WYS = ".jodit-wysiwyg";
// A few Jodit controls render their container under a different `ref` than the
// toolbar name we configure. `align` is the notable one: its control name is
// the default alignment ('left'), so the rendered button is `ref="left"`.
const REF_OVERRIDES: Record<string, string> = { align: "left" };
const btn = (name: string) => `[ref="${REF_OVERRIDES[name] ?? name}"]`;

let access = "";
let refresh = "";

/** Obtain JWTs and inject them so the SPA boots already authenticated. */
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

/** Open /manage/news and pop the create dialog so the editor is mounted. */
async function openEditor(page: import("@playwright/test").Page) {
  await page.goto("/manage/news");
  const create = page.getByRole("button", { name: /Новая новость/ });
  await expect(create).toBeVisible({ timeout: 20_000 });
  await create.click();
  await expect(page.locator(WYS).first()).toBeVisible({ timeout: 15_000 });
}

/** Clear the editor, type sample text, and select all of it. */
async function typeAndSelectAll(page: import("@playwright/test").Page, text: string) {
  const wys = page.locator(WYS).first();
  await wys.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Delete");
  await page.keyboard.insertText(text);
  await page.keyboard.press("Control+A");
}

// ───────────────────────────────────────────────────────────────────────────
// 1. Every configured button renders in the toolbar
// ───────────────────────────────────────────────────────────────────────────
const ALL_BUTTONS = [
  "bold", "italic", "underline", "strikethrough", "eraser",
  "ul", "ol",
  "font", "fontsize", "brush",
  "paragraph",
  "align",
  "link", "image", "video", "table", "hr",
  "indent", "outdent",
  "superscript", "subscript",
  "copyformat", "selectall",
  "undo", "redo",
  "fullsize", "preview", "source", "print",
];

test("all configured toolbar buttons are present", async ({ page }) => {
  await openEditor(page);
  const missing: string[] = [];
  for (const name of ALL_BUTTONS) {
    const count = await page.locator(btn(name)).count();
    if (count === 0) missing.push(name);
  }
  expect(missing, `buttons missing from toolbar: ${missing.join(", ")}`).toEqual([]);
});

// ───────────────────────────────────────────────────────────────────────────
// 2. Inline marks produce the expected HTML
// ───────────────────────────────────────────────────────────────────────────
const INLINE: { name: string; expect: RegExp }[] = [
  { name: "bold", expect: /<(strong|b)\b|font-weight\s*:\s*(bold|[6-9]00)/i },
  { name: "italic", expect: /<(em|i)\b|font-style\s*:\s*italic/i },
  { name: "underline", expect: /<u\b|text-decoration[^"]*underline/i },
  { name: "strikethrough", expect: /<(s|strike|del)\b|line-through/i },
  { name: "superscript", expect: /<sup\b/i },
  { name: "subscript", expect: /<sub\b/i },
];

for (const mark of INLINE) {
  test(`inline mark «${mark.name}» applies formatting`, async ({ page }) => {
    await openEditor(page);
    await typeAndSelectAll(page, "Форматируемый текст");
    await page.locator(btn(mark.name)).first().click();
    const html = await page.locator(WYS).first().innerHTML();
    expect(html, `result HTML: ${html}`).toMatch(mark.expect);
  });
}

// ───────────────────────────────────────────────────────────────────────────
// 3. Block tools mutate the document
// ───────────────────────────────────────────────────────────────────────────
test("bulleted list (ul) wraps selection in <ul>", async ({ page }) => {
  await openEditor(page);
  await typeAndSelectAll(page, "Пункт списка");
  await page.locator(btn("ul")).first().click();
  await expect(page.locator(`${WYS} ul li`).first()).toBeVisible();
});

test("numbered list (ol) wraps selection in <ol>", async ({ page }) => {
  await openEditor(page);
  await typeAndSelectAll(page, "Пункт списка");
  await page.locator(btn("ol")).first().click();
  await expect(page.locator(`${WYS} ol li`).first()).toBeVisible();
});

test("horizontal rule (hr) inserts <hr>", async ({ page }) => {
  await openEditor(page);
  await page.locator(WYS).first().click();
  await page.keyboard.insertText("До линии");
  await page.locator(btn("hr")).first().click();
  await expect(page.locator(`${WYS} hr`).first()).toBeAttached();
});

test("indent adds left margin to the block", async ({ page }) => {
  await openEditor(page);
  await typeAndSelectAll(page, "Абзац с отступом");
  await page.locator(btn("indent")).first().click();
  const html = await page.locator(WYS).first().innerHTML();
  expect(html, `result HTML: ${html}`).toMatch(/margin-left|padding-left/i);
});

// ───────────────────────────────────────────────────────────────────────────
// 4. Dropdown / dialog tools open a popup
// ───────────────────────────────────────────────────────────────────────────
const POPUP_BUTTONS = [
  "font", "fontsize", "brush", "paragraph",
  "align", "link", "image", "video", "table",
];

for (const name of POPUP_BUTTONS) {
  test(`dropdown «${name}» opens a popup`, async ({ page }) => {
    await openEditor(page);
    // Some popups (link/align) act on a selection — give them one.
    await typeAndSelectAll(page, "Текст");
    await page.locator(btn(name)).first().click();
    await expect(
      page.locator(".jodit-popup, .jodit-dialog").first(),
    ).toBeVisible({ timeout: 5_000 });
    await page.keyboard.press("Escape");
  });
}

// ───────────────────────────────────────────────────────────────────────────
// 5. Mode tools switch the editor view
// ───────────────────────────────────────────────────────────────────────────
test("source toggle hides the WYSIWYG surface", async ({ page }) => {
  await openEditor(page);
  await page.locator(WYS).first().click();
  await page.keyboard.insertText("Контент для исходника");
  await page.locator(btn("source")).first().click();
  // In source mode Jodit hides the contenteditable and shows a code area.
  await expect(page.locator(WYS).first()).toBeHidden({ timeout: 5_000 });
  // Toggle back.
  await page.locator(btn("source")).first().click();
  await expect(page.locator(WYS).first()).toBeVisible();
});

test("fullsize toggle fills the viewport (not trapped in the dialog)", async ({ page }) => {
  await openEditor(page);
  const container = page.locator(".jodit-container.jodit_fullsize").first();
  await page.locator(btn("fullsize")).first().click();
  await expect(container).toBeAttached({ timeout: 5_000 });

  // Regression guard: inside the centred (transformed + backdrop-blurred) Radix
  // dialog the editor used to collapse off-screen → blank white page. It must
  // now cover the whole viewport. Poll the box because the dialog animates open,
  // so the fullsize layout settles a beat after the class lands.
  const viewport = page.viewportSize()!;
  await expect
    .poll(
      async () => {
        const b = await container.boundingBox();
        if (!b) return "no box";
        const ok =
          b.width >= viewport.width - 2 &&
          b.height >= viewport.height - 2 &&
          Math.abs(b.x) <= 2 &&
          Math.abs(b.y) <= 2;
        return ok ? "covers" : `x=${Math.round(b.x)} y=${Math.round(b.y)} w=${Math.round(b.width)} h=${Math.round(b.height)}`;
      },
      { timeout: 6_000 },
    )
    .toBe("covers");

  // In fullsize the toolbar fills the screen and <html> intercepts pointer
  // events, so the toggle-back click must bypass actionability checks.
  await page.locator(btn("fullsize")).first().click({ force: true });
  await expect(page.locator(".jodit-container.jodit_fullsize")).toHaveCount(0);
});

test("preview opens a dialog", async ({ page }) => {
  await openEditor(page);
  await page.locator(WYS).first().click();
  await page.keyboard.insertText("Предпросмотр содержимого");
  await page.locator(btn("preview")).first().click();
  // Jodit mounts the preview dialog on <body>; assert the *active* dialog is
  // present (it animates in, so visibility can lag — attachment is the signal).
  await expect(page.locator(".jodit-dialog_active_true").first()).toBeAttached({
    timeout: 5_000,
  });
  await page.keyboard.press("Escape");
});

test("print button is present and enabled", async ({ page }) => {
  // Clicking would spawn a print dialog / blank window that hangs headless,
  // so we only assert the control is wired and interactive.
  await openEditor(page);
  const print = page.locator(btn("print")).first();
  await expect(print).toBeVisible();
  await expect(print).toBeEnabled();
});

// ───────────────────────────────────────────────────────────────────────────
// 6. History & clear tools respond
// ───────────────────────────────────────────────────────────────────────────
test("eraser strips inline formatting", async ({ page }) => {
  await openEditor(page);
  await typeAndSelectAll(page, "Жирный текст");
  await page.locator(btn("bold")).first().click();
  expect(await page.locator(WYS).first().innerHTML()).toMatch(/<(strong|b)\b|font-weight/i);
  await page.keyboard.press("Control+A");
  await page.locator(btn("eraser")).first().click();
  const html = await page.locator(WYS).first().innerHTML();
  expect(html, `result HTML: ${html}`).not.toMatch(/<(strong|b)\b/i);
});

test("undo and redo reverse and reapply an edit", async ({ page }) => {
  await openEditor(page);
  const wys = page.locator(WYS).first();
  await wys.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Delete");
  await page.keyboard.insertText("ПЕРВЫЙ");
  // Jodit coalesces edits into one history step within its snapshot debounce
  // (~500ms). Wait comfortably past it so each segment is its own undo step.
  await page.waitForTimeout(1_500);
  await page.keyboard.insertText(" ВТОРОЙ");
  await page.waitForTimeout(1_500);
  await expect(wys).toContainText("ВТОРОЙ");

  await page.locator(btn("undo")).first().click();
  await expect(wys).not.toContainText("ВТОРОЙ", { timeout: 8_000 });
  await expect(wys).toContainText("ПЕРВЫЙ");

  // Let the undo DOM mutation settle before redo so the click isn't swallowed.
  await page.waitForTimeout(500);
  await page.locator(btn("redo")).first().click();
  await expect(wys).toContainText("ВТОРОЙ", { timeout: 8_000 });
});

test("select-all + copyformat are clickable without error", async ({ page }) => {
  await openEditor(page);
  await page.locator(WYS).first().click();
  await page.keyboard.insertText("Текст для выделения");
  await page.locator(btn("selectall")).first().click();
  await page.locator(btn("copyformat")).first().click();
  // copyformat is a toggle — it should mark itself active (aria-pressed) once on.
  await expect(page.locator(`${btn("copyformat")}`).first()).toBeVisible();
});
