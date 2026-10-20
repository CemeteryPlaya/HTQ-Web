/**
 * Портал поставщика тендера (T3.5; план этапа 3 §1, §2 T3.5).
 *
 * Сценарий: закупщик (СН) готовит тендер API-вызовами (заявка → части-ЗЗ
 * утверждены ТД и ОД → тендер с желаемой схемой оплаты → потенциальный
 * поставщик → публикация, ссылка); поставщик открывает ссылку на «телефоне»
 * (контекст A), привязывает устройство — cookie ставится на стенд
 * `http://group.localhost:3000` (небезопасная cookie стенда,
 * `TENDER_PORTAL_INSECURE_COOKIE`), — заполняет цену и сохраняет черновик;
 * второе устройство (контекст B) с той же ссылкой получает отказ «Ссылка
 * открыта на другом устройстве», а первое продолжает работать.
 *
 * Стенд: `docker compose -f docker-compose.test-local.yml up -d --build`,
 * `./scripts/bpp-e2e-seed.sh`, затем роли тендерного модуля
 * `manage.py tender_assign_roles --company hi-tech-group` (СН — «Менеджер по
 * закупкам» → `tender-buyer`). Готовую ссылку можно передать вместо
 * подготовки: `E2E_TENDER_PORTAL_LINK=<…/supplier/<token>>`.
 *
 * Запуск: `npx playwright test tests/e2e/40_tender_portal.spec.ts --project=chromium`.
 */
import type { APIRequestContext, Browser, BrowserContext } from "@playwright/test";

import {
  Api, BPP_BASE, approveRoute, articleId, createApprovedBudget, createProject, expect, isoToday,
  test, uniq,
} from "./bpp_fixtures";

const PHONE = { width: 390, height: 844 };

/** Путь `/supplier/<token>` из ссылки сервера (её корень — боевой домен, а не стенд). */
function portalPath(link: string): string {
  const path = link.startsWith("http") ? new URL(link).pathname : link;
  expect(path, `ссылка портала: ${link}`).toMatch(/^\/supplier\/[A-Za-z0-9_-]+$/);
  return path;
}

/** PUT у `Api` фикстур нет — берём его контекст запросов. */
function rawContext(api: Api): APIRequestContext {
  return (api as unknown as { ctx: APIRequestContext }).ctx;
}

/** Тендер в приёме предложений с одним приглашённым потенциальным поставщиком; ссылка. */
async function publishedTenderLink(): Promise<string> {
  if (process.env.E2E_TENDER_PORTAL_LINK) return process.env.E2E_TENDER_PORTAL_LINK;
  const tag = uniq();
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const buyer = await Api.as("sn");
  try {
    const project = await createProject(fd, pm, `TN${tag}`);
    const article = await articleId(fd, "E2E-MET");
    await createApprovedBudget(fd, project.id, [{ article_id: article, limit_amount: "50000000.00" }]);

    const uoms: { id: string; code: string }[] = await buyer.get("/api/refdata/v1/uoms?active=true");
    const pcs = uoms.find((u) => u.code === "pcs") ?? uoms[0];
    const need = isoToday(30);
    const draft = await buyer.post("/api/tender/v1/requests", {
      initiator_role: "sn",
      project_id: project.id,
      article_id: article,
      purchase_type: "goods",
      need_date: need,
      delivery_address: "Астана, объект е2е",
      justification: "Тендер для сценария портала поставщика (е2е), не короче десяти знаков",
      items: [{ name: `Швеллер 12П е2е ${tag}`, specs: "ГОСТ 8240", uom_id: pcs.id, qty: "10", plan_price: "36500", need_date: need }],
    });
    const sent = await buyer.post(`/api/tender/v1/requests/${draft.id}/submit`, { version: draft.version });
    for (const part of sent.parts) await approveRoute(part.bpp_request_id, ["td", "od"]);
    const approved = await buyer.get(`/api/tender/v1/requests/${draft.id}`);
    expect(approved.status, `заявка ${approved.number}`).toBe("approved");

    const deadline = new Date(Date.now() + 2 * 86_400_000).toISOString();
    const tender = await buyer.post("/api/tender/v1/tenders", {
      request_id: draft.id, deadline_at: deadline, currency_code: "KZT", delivery_terms: "DAP объект",
    });
    const scheme = await rawContext(buyer).put(`/api/tender/v1/tenders/${tender.id}/payment-scheme`, {
      data: { kind: "prepay" },
    });
    expect(scheme.ok(), `схема оплаты: ${scheme.status()} ${await scheme.text()}`).toBeTruthy();
    const prospect = await buyer.post("/api/tender/v1/prospects", {
      name: `ИП Е2Е поставщик ${tag}`, email: `supplier-${tag}@e2e.example.kz`, reg_number: "", country_code: "KZ",
    });
    await buyer.post(`/api/tender/v1/tenders/${tender.id}/invitations`, { prospect_id: prospect.id });
    const fresh = await buyer.get(`/api/tender/v1/tenders/${tender.id}`);
    const { links } = await buyer.post(`/api/tender/v1/tenders/${tender.id}/publish`, { version: fresh.version });
    expect(links, "ссылки публикации").toHaveLength(1);
    return links[0].link;
  } finally {
    await Promise.all([fd.dispose(), pm.dispose(), buyer.dispose()]);
  }
}

async function device(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({ baseURL: BPP_BASE, viewport: PHONE, ignoreHTTPSErrors: true });
  await context.addInitScript(() => window.localStorage.setItem("i18nextLng", "ru"));
  context.setDefaultTimeout(20_000);
  return context;
}

test.describe("портал поставщика", () => {
  test("одно устройство на ссылку: второе получает отказ, первое работает дальше", async ({ browser }) => {
    test.setTimeout(240_000);
    const path = portalPath(await publishedTenderLink());

    const phone = await device(browser);
    const other = await device(browser);
    try {
      // ── устройство A: карточка → привязка → форма ──────────────────
      const a = await phone.newPage();
      await a.goto(path);
      await expect(a.getByText(/закрепится за этим устройством/)).toBeVisible({ timeout: 30_000 });
      await a.getByRole("button", { name: "Открыть предложение" }).click();
      await expect(a.getByRole("heading", { name: /Тендер ТН-/ })).toBeVisible();

      const cookie = (await phone.cookies()).find((c) => /tender_device$/.test(c.name));
      expect(cookie, "cookie устройства на стенде").toBeTruthy();
      expect(cookie!.httpOnly).toBe(true);
      expect(cookie!.sameSite).toBe("Strict");
      expect(cookie!.path).toBe("/api/tender/v1/supplier/");
      // Стенд по http: TENDER_PORTAL_INSECURE_COOKIE — без Secure и без префикса
      // __Secure- (такую cookie браузер по http не принял бы вовсе).
      expect(cookie!.secure).toBe(false);
      expect(cookie!.name).toBe("tender_device");
      expect(new URL(BPP_BASE).hostname).toContain(cookie!.domain.replace(/^\./, ""));

      await a.getByLabel(/^Цена за единицу: Швеллер 12П/).fill("35000");
      await a.getByRole("button", { name: "Сохранить черновик" }).click();
      await expect(a.getByText("Черновик сохранён")).toBeVisible();

      // ── устройство B: та же ссылка — отказ ─────────────────────────
      const b = await other.newPage();
      await b.goto(path);
      await b.getByRole("button", { name: "Открыть предложение" }).click();
      await expect(b.getByRole("heading", { name: "Ссылка открыта на другом устройстве" })).toBeVisible();
      expect((await other.cookies()).some((c) => /tender_device$/.test(c.name) && c.value)).toBeFalsy();

      // ── устройство A после отказа B — по-прежнему в форме ──────────
      await a.reload();
      await expect(a.getByLabel(/^Цена за единицу: Швеллер 12П/)).toHaveValue(/35\s?000/);
    } finally {
      await phone.close();
      await other.close();
    }
  });

  test("неизвестный токен — «Ссылка недействительна»", async ({ browser }) => {
    const context = await device(browser);
    try {
      const page = await context.newPage();
      await page.goto(`/supplier/unknown-${uniq()}-token`);
      await expect(page.getByRole("heading", { name: "Ссылка недействительна" })).toBeVisible({ timeout: 30_000 });
    } finally {
      await context.close();
    }
  });
});
