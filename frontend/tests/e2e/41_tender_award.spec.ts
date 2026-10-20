/**
 * Вскрытие, сравнение, выбор, утверждение и передача в БЗО (этап 5, T5.6;
 * спека этапа 5 §3 T5.6).
 *
 * Сценарий: закупщик (СН) готовит тендер API-вызовами (заявка из двух
 * позиций → части-ЗЗ утверждены ТД и ОД → тендер с предоплатой → два
 * потенциальных поставщика с БИН → публикация); оба поставщика подают
 * предложения через портал (API: привязка устройства cookie, черновик,
 * отправка) — А дешевле по первой позиции, Б по второй. Закупщик в браузере:
 * «Вскрыть» (все ответили — срок ждать не нужно) → «Сравнение»: самый
 * дешёвый подсвечен → «Выбор»: обе позиции у А, у второй (не самая дешёвая)
 * комментарий строки и общий → «На утверждение». ТД (проверка качества) и ФД
 * утверждают своими учётками; закупщик «Передать в БЗО» — во вкладке
 * «Поставка» документы БЗО ссылками.
 *
 * Стенд: `docker compose -f docker-compose.test-local.yml up -d --build`,
 * `./scripts/bpp-e2e-seed.sh`, затем по компании `hi-tech-group`:
 * `manage.py migrate_companies`, `manage.py tender_assign_roles` и
 * `manage.py tender_configure_route` (маршрут `tender.award` «Проверка
 * качества → ФД»).
 *
 * Запуск: `npx playwright test tests/e2e/41_tender_award.spec.ts --project=chromium`.
 */
import { request as pwRequest, type APIRequestContext } from "@playwright/test";

import {
  Api, BPP_API, BPP_BASE, HOST_LABEL, approveRoute, articleId, createApprovedBudget, createProject, expect,
  isoToday, openAs, scenario, uniq, uniqueBin,
} from "./bpp_fixtures";

/** PUT у `Api` фикстур нет — берём его контекст запросов. */
function rawContext(api: Api): APIRequestContext {
  return (api as unknown as { ctx: APIRequestContext }).ctx;
}

interface Prepared {
  tenderId: string;
  number: string;
  names: [string, string];
}

/** Поставщик подаёт предложение через портал: привязка устройства → черновик → отправка. */
async function submitOffer(link: string, prices: [string, string]) {
  const token = new URL(link, "http://x").pathname.split("/").pop();
  const base = `/api/tender/v1/supplier/${token}`;
  // Портал принимает запись только со страницы своей компании (`check_origin`).
  const ctx = await pwRequest.newContext({
    baseURL: BPP_API, extraHTTPHeaders: { "X-HTQ-Company": HOST_LABEL, Origin: BPP_BASE },
  });
  try {
    const bind = await ctx.post(`${base}/bind`, { data: {} });
    expect(bind.ok(), `привязка устройства: ${bind.status()} ${await bind.text()}`).toBeTruthy();
    const tender = await (await ctx.get(`${base}/tender`)).json();
    const offer = await (await ctx.get(`${base}/offer`)).json();
    const saved = await ctx.put(`${base}/offer`, {
      data: {
        version: offer.version,
        currency_code: "KZT",
        with_vat: false,
        valid_until: isoToday(30),
        lines: tender.items.map((item: { id: string; qty: string }, i: number) => ({
          item_id: item.id, participates: true, price: prices[i], qty: item.qty,
          delivery_date: isoToday(20),
        })),
        payment_scheme: { kind: "prepay" },
      },
    });
    expect(saved.ok(), `черновик предложения: ${saved.status()} ${await saved.text()}`).toBeTruthy();
    const draft = await saved.json();
    const sent = await ctx.post(`${base}/offer/submit`, { data: { version: draft.version, pd_consent: true } });
    expect(sent.ok(), `отправка предложения: ${sent.status()} ${await sent.text()}`).toBeTruthy();
  } finally {
    await ctx.dispose();
  }
}

/** Тендер на приёме, оба поставщика подали предложения. */
async function preparedTender(): Promise<Prepared> {
  const tag = uniq();
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const buyer = await Api.as("sn");
  try {
    const project = await createProject(fd, pm, `TA${tag}`);
    const article = await articleId(fd, "E2E-MET");
    await createApprovedBudget(fd, project.id, [{ article_id: article, limit_amount: "50000000.00" }]);

    const uoms: { id: string; code: string }[] = await buyer.get("/api/refdata/v1/uoms?active=true");
    const pcs = uoms.find((u) => u.code === "pcs") ?? uoms[0];
    const need = isoToday(30);
    const draft = await buyer.post("/api/tender/v1/requests", {
      initiator_role: "sn", project_id: project.id, article_id: article, purchase_type: "goods",
      need_date: need, delivery_address: "Астана, объект е2е",
      justification: "Тендер для сценария выбора поставщиков (е2е), не короче десяти знаков",
      items: [
        { name: `Швеллер 12П е2е ${tag}`, specs: "ГОСТ 8240", uom_id: pcs.id, qty: "10", plan_price: "36500", need_date: need },
        { name: `Уголок 50×5 е2е ${tag}`, specs: "ГОСТ 8509", uom_id: pcs.id, qty: "4", plan_price: "21500", need_date: need },
      ],
    });
    const sent = await buyer.post(`/api/tender/v1/requests/${draft.id}/submit`, { version: draft.version });
    for (const part of sent.parts) await approveRoute(part.bpp_request_id, ["td", "od"]);

    const tender = await buyer.post("/api/tender/v1/tenders", {
      request_id: draft.id, deadline_at: new Date(Date.now() + 2 * 86_400_000).toISOString(),
      currency_code: "KZT", delivery_terms: "DAP объект",
    });
    const scheme = await rawContext(buyer).put(`/api/tender/v1/tenders/${tender.id}/payment-scheme`, { data: { kind: "prepay" } });
    expect(scheme.ok(), `схема оплаты: ${scheme.status()}`).toBeTruthy();
    const names: [string, string] = [`ТОО «Е2Е Альфа ${tag}»`, `ТОО «Е2Е Бета ${tag}»`];
    for (const [i, name] of names.entries()) {
      const prospect = await buyer.post("/api/tender/v1/prospects", {
        name, email: `award-${i}-${tag}@e2e.example.kz`, reg_number: uniqueBin(), country_code: "KZ",
      });
      await buyer.post(`/api/tender/v1/tenders/${tender.id}/invitations`, { prospect_id: prospect.id });
    }
    const fresh = await buyer.get(`/api/tender/v1/tenders/${tender.id}`);
    const { links } = await buyer.post(`/api/tender/v1/tenders/${tender.id}/publish`, { version: fresh.version });
    expect(links, "ссылки публикации").toHaveLength(2);
    // А дешевле по швеллеру, Б — по уголку.
    await submitOffer(links[0].link, ["35000", "22000"]);
    await submitOffer(links[1].link, ["36000", "20500"]);
    return { tenderId: tender.id, number: tender.number, names };
  } finally {
    await Promise.all([fd.dispose(), pm.dispose(), buyer.dispose()]);
  }
}

scenario("вскрытие, сравнение, выбор с комментарием, ТД и ФД утверждают, передача в БЗО", async (browser) => {
  const { tenderId, number, names: [alpha, beta] } = await preparedTender();
  const { page } = await openAs(browser, "sn");
  await page.goto(`/tender/tenders/${tenderId}`);
  await expect(page.getByRole("heading", { name: `Тендер ${number}` })).toBeVisible({ timeout: 30_000 });

  // ── вскрытие ─────────────────────────────────────────────────────────
  await page.getByRole("button", { name: "Вскрыть" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Вскрыть" }).click();
  const comparison = page.getByTestId("comparison-items");
  await expect(comparison).toBeVisible();
  await expect(comparison.getByRole("columnheader", { name: alpha })).toBeVisible();
  await expect(comparison.getByRole("columnheader", { name: beta })).toBeVisible();
  // Самый дешёвый уголок — у Б, его клетка подсвечена.
  const angle = comparison.getByRole("row").filter({ hasText: "Уголок 50×5" });
  await expect(angle.locator('td[data-cheapest="true"]')).toContainText("20 500,00");

  // ── выбор ────────────────────────────────────────────────────────────
  await page.getByRole("tab", { name: "Выбор" }).click();
  for (const n of [1, 2]) {
    await page.getByRole("combobox", { name: `Поставщик позиции ${n}` }).click();
    await page.getByRole("option", { name: new RegExp(alpha.replace(/[«»]/g, ".")) }).click();
  }
  await page.getByRole("textbox", { name: "Комментарий к позиции 2" })
    .fill("Один поставщик на обе позиции — одна поставка");
  await page.getByLabel("Комментарий к выбору").fill("Берём всё у одного поставщика: одна доставка и один счёт");
  await page.getByRole("button", { name: "Сохранить выбор" }).click();
  await expect(page.getByText("Выбор сохранён")).toBeVisible();
  await page.getByRole("button", { name: "На утверждение" }).click();
  await expect(page.getByText("Выбор отправлен на утверждение")).toBeVisible();

  // ── утверждение: проверка качества (ТД) → ФД ─────────────────────────
  await approveRoute(tenderId, ["td", "fd"]);

  // ── передача в БЗО ───────────────────────────────────────────────────
  await page.reload();
  await page.getByRole("button", { name: "Передать в БЗО" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Передать в БЗО" }).click();
  await expect(page.getByText(/Передано в БЗО: (СЧ|ДГ)-/)).toBeVisible();
  await expect(page.getByRole("tab", { name: "Поставка" })).toHaveAttribute("aria-selected", "true");
  const delivery = page.getByTestId("tender-delivery");
  await expect(delivery.getByText(alpha)).toBeVisible();
  const document = delivery.getByRole("link", { name: /^(СЧ|ДГ)-\d{4}-\d{6}$/ }).first();
  await expect(document).toHaveAttribute("href", /^\/bpp\/(invoices|agreements)\//);
});
