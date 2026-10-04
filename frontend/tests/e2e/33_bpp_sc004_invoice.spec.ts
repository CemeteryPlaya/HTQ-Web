/**
 * SC-004. Счёт без договора (ТЗ §28.2; ранбук, шаг 16).
 *
 * СН: отметить позиции, «Оформить счёт», основание «Без договора», контрагент,
 * номер, дата, сумма, файл. Ожидается: сумма > 4 325 000 тг (1000 МРП при МРП
 * 4 325) — отправка заблокирована, предложен договор (E-INV-01); сумма ≤ порога —
 * уходит ФД, присвоен номер `СЧ-ГГГГ-NNNNNN`.
 *
 * Условия (API): проект с бюджетом по «Металлопрокату», утверждённая заявка СН на
 * позицию стоимостью 5 000 000 ₸ (позиция — в Плане закупок СН), контрагент.
 */
import {
  Api, BPP_BASE, INVOICE_THRESHOLD, articleId, attachFile, createApprovedBudget,
  createApprovedRequest, createCounterparty, createProject, expect, openAs, pdfFile,
  scenario, test, uniq,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

scenario("SC-004: счёт без договора — выше порога отказ с предложением договора, в пределах порога уходит ФД", async (browser) => {
  const tag = `SC4-${uniq()}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const sn = await Api.as("sn");
  const project = await createProject(fd, pm, tag);
  const metId = await articleId(fd, "E2E-MET");
  await createApprovedBudget(fd, project.id, [{ article_id: metId, limit_amount: "20000000" }]);
  const counterparty = await createCounterparty(fd, tag);
  await createApprovedRequest(sn, "sn", project.id, metId, [
    { name: "Дизель-генератор 200 кВт", qty: "1", price: "5000000" },
  ]);

  const { page } = await openAs(browser, "sn");
  await page.goto("/bpp/plan");
  await page.getByRole("combobox", { name: "Проект" }).click();
  await page.getByRole("option", { name: new RegExp(project.code) }).click();
  await expect(page.getByTestId("plan-item")).toHaveCount(1);
  await page.getByTestId("plan-item").getByRole("checkbox").check();
  await page.getByRole("button", { name: "Оформить счёт" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page).toHaveURL(/\/bpp\/invoices\/[0-9a-f-]{36}/);

  // Основание — «Без договора».
  await expect(page.getByText("Без договора", { exact: true }).first()).toBeVisible();

  await page.locator("#inv-counterparty").click();
  await page.locator("#inv-counterparty").fill(counterparty.name);
  await page.getByRole("button", { name: new RegExp(counterparty.bin) }).click();
  await page.locator("#inv-ext-number").fill(`С-${tag}`);
  const now = new Date();
  await page.locator("#inv-ext-date").fill(
    `${String(now.getDate()).padStart(2, "0")}${String(now.getMonth() + 1).padStart(2, "0")}${now.getFullYear()}`,
  );
  await page.getByText("ТМЦ", { exact: true }).click();

  // Сумма выше порога: 5 000 000 > 4 325 000 (1000 МРП при МРП 4 325).
  await page.locator("#inv-amount").fill("5000000");
  await page.locator("#inv-amount").blur();
  await attachFile(page, /^Счёт на оплату$/, pdfFile("schet.pdf"));
  await expect(page.getByRole("alert").filter({ hasText: /1000 МРП/ })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(/4[\s\u00a0\u202f]325[\s\u00a0\u202f]000/);
  await expect(
    page.getByRole("button", { name: "Оформить договор по этим позициям" }),
  ).toBeVisible();

  // Отправка заблокирована: кнопки «Отправить ФД» над порогом нет, счёт остаётся «Черновиком».
  await expect(page.getByRole("button", { name: "Отправить ФД" })).toHaveCount(0);
  await expect(page.getByText("Черновик", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("На рассмотрении ФД", { exact: true })).toHaveCount(0);

  // Сервер держит то же правило, что и экран: отправка сверх порога — 422 E-INV-01
  // с текстом ТЗ (кнопки в UI нет, поэтому проверяем запросом к API по сохранённому черновику).
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.getByText("Есть несохранённые изменения")).toHaveCount(0);
  const invoiceId = page.url().match(/invoices\/([0-9a-f-]{36})/)![1];
  const refusal = await sn.postRaw(`/api/bpp/v1/invoices/${invoiceId}/submit`, {});
  expect(refusal.status, JSON.stringify(refusal.body)).toBe(422);
  expect(refusal.body.code).toBe("E-INV-01");
  expect(refusal.body.detail).toMatch(/превышает 1000 МРП/);

  // Сумма в пределах порога — счёт уходит ФД, присвоен номер СЧ-ГГГГ-NNNNNN.
  const ok = INVOICE_THRESHOLD - 325_000; // 4 000 000
  await page.locator("#inv-amount").fill(String(ok));
  await page.locator("#inv-amount").blur();
  const lineAmount = page.getByTestId("invoice-line").getByLabel(/Сумма в счёте/);
  await lineAmount.fill(String(ok));
  await lineAmount.blur();
  await expect(page.getByRole("alert").filter({ hasText: /1000 МРП/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Отправить ФД" }).click();
  await expect(page.getByText("На рассмотрении ФД", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: /СЧ-\d{4}-\d{6}/ }).or(
    page.getByText(/СЧ-\d{4}-\d{6}/).first(),
  ).first()).toBeVisible();
});
