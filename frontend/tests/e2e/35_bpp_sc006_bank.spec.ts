/**
 * SC-006. Сверка оплат (ТЗ §28.2; ранбук, шаг 16).
 *
 * ФД: «Оплаты факт», банк, формат, период, файл выписки. Ожидается: загрузка
 * «Сверена»; «Требуют проверки» и «Не сопоставлены» разбираются вручную (подтверждение и исключение); в реестре
 * счетов виден статус сверки, дашборд «Оплаты» показывает итоги.
 *
 * Условия (API): проект с бюджетом, счёт без договора на 3 000 000 ₸ доведён до
 * «Оплачено» отметкой БУХ (SC-004/SC-005 проверяют эти шаги экранами); счёт
 * организации и шаблон 1С заведены `scripts/bpp-e2e-seed.sh`. Выписка — файл 1С
 * (`onecStatement`) с двумя списаниями: номер счёта в назначении, но чужой БИН (→ «Требует проверки»), и платёж без номера.
 * Автосверку делает Celery-воркер сразу после разбора.
 */
import {
  Api, BPP_BASE, ORG_IBAN, articleId, createApprovedBudget, createApprovedRequest,
  createCounterparty, createProject, createSubmittedInvoice, ddmmyyyy, expect, isoToday,
  onecStatement, openAs, scenario, test, uniq, uniqueBin,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

scenario("SC-006: ФД загружает выписку 1С — «Сверена», ручной разбор «Требуют проверки» и «Не сопоставлены», статус сверки в реестре и дашборд", async (browser) => {
  const tag = `SC6-${uniq()}`;
  const extNumber = `С-${tag}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const sn = await Api.as("sn");
  const buh = await Api.as("buh");
  const project = await createProject(fd, pm, tag);
  const metId = await articleId(fd, "E2E-MET");
  await createApprovedBudget(fd, project.id, [{ article_id: metId, limit_amount: "20000000" }]);
  const counterparty = await createCounterparty(fd, tag);
  await createApprovedRequest(sn, "sn", project.id, metId, [
    { name: "Кабельная продукция", qty: "1", price: "3000000" },
  ]);
  const invoice = await createSubmittedInvoice(sn, "sn", project.id, counterparty, {
    amount: "3000000", purchaseType: "goods", extNumber,
  });
  await fd.post(`/api/bpp/v1/invoices/${invoice.id}/decision`, { decision: "pay" });
  const paid = await buh.post(`/api/bpp/v1/invoices/${invoice.id}/payments`, {
    pay_date: isoToday(), amount: "3000000", pp_number: "ПП-E2E",
  });
  expect(paid.status).toBe("paid");

  const today = ddmmyyyy(new Date());
  const weekAgo = ddmmyyyy(new Date(Date.now() - 7 * 86_400_000));
  const statement = onecStatement(ORG_IBAN, [
    {
      number: `A${tag}`, date: today, amount: "3000000.00",
      // БИН получателя ≠ БИН контрагента счёта → «Требует проверки» (ТЗ §11.3).
      recipientBin: uniqueBin(), recipient: counterparty.name,
      purpose: `Оплата по счёту ${invoice.number} за кабельную продукцию`,
    },
    {
      number: `B${tag}`, date: today, amount: "12345.67",
      recipientBin: "123456789012", recipient: "ТОО Прочий получатель",
      purpose: "Прочий платёж без номера счёта",
    },
  ], [weekAgo, today]);

  // ── ФД: «Оплаты факт» → «Загрузить выписку» ─────────────────────────
  const { page } = await openAs(browser, "fd");
  await page.goto("/bpp/bank");
  await page.getByRole("link", { name: "Загрузить выписку" }).or(
    page.getByRole("button", { name: "Загрузить выписку" }),
  ).click();
  await expect(page).toHaveURL(/\/bpp\/bank\/new/);
  await page.locator("#imp-account").click();
  await page.getByRole("option", { name: new RegExp(ORG_IBAN) }).click();
  await expect(page.getByTestId("import-format")).toContainText(/1С/i);
  await page.locator("#imp-file").setInputFiles(statement);
  await page.getByRole("button", { name: "Загрузить", exact: true }).click();
  await expect(page).toHaveURL(/\/bpp\/bank\/[0-9a-f-]{36}/);

  // Загрузка «Сверена» (разбор и автосверка идут в фоне — экран опрашивает сам).
  await expect(page.getByText("Сверена", { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  // Вкладки сверки: строка со счётом, но с чужим БИН — «Требуют проверки»;
  // платёж без номера — «Не сопоставлены».
  await page.getByRole("tab", { name: /Требуют проверки/ }).click();
  const reviewRow = page.getByRole("row").filter({ hasText: invoice.number });
  await expect(reviewRow).toHaveCount(1);

  // Ручной разбор: «Подтвердить» с комментарием ≥ 10 символов (BR-060) → «Сопоставлены».
  await reviewRow.getByRole("button", { name: "Подтвердить" }).click();
  const confirmDialog = page.getByRole("dialog");
  await confirmDialog.locator("textarea").fill("БИН получателя проверен вручную, платёж по этому счёту");
  await confirmDialog.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(reviewRow).toHaveCount(0);
  await page.getByRole("tab", { name: /Сопоставлены/ }).click();
  await expect(page.getByText(invoice.number).first()).toBeVisible();
  await page.getByRole("tab", { name: /Не сопоставлены/ }).click();
  await expect(page.getByText("Прочий платёж без номера счёта").first()).toBeVisible();

  // Ручной разбор непривязанной строки: «Исключить — не относится к закупкам».
  const lineRow = page.getByRole("row").filter({ hasText: "Прочий платёж без номера счёта" });
  await lineRow.getByRole("button", { name: /Исключить/ }).click();
  const excludeDialog = page.getByRole("dialog");
  await excludeDialog.locator("textarea").fill("Платёж не относится к закупкам, разбор сценария приёмки");
  await excludeDialog.getByRole("button", { name: "Исключить", exact: true }).click();
  await expect(lineRow).toHaveCount(0);
  await page.getByRole("tab", { name: /Исключены/ }).click();
  await expect(page.getByText("Прочий платёж без номера счёта").first()).toBeVisible();

  // ── Реестр счетов: статус сверки «Оплачен полностью» ────────────────
  await page.goto("/bpp/invoices");
  await page.getByPlaceholder(/Номер, номер счёта контрагента/).fill(extNumber);
  const invoiceRow = page.getByRole("row").filter({ hasText: invoice.number });
  await expect(invoiceRow).toHaveCount(1);
  await expect(invoiceRow).toContainText("Оплачен полностью");

  // ── Дашборд «Оплаты»: итоги по проекту ──────────────────────────────
  await page.goto("/bpp/dashboard");
  await page.locator("#dash-project").click();
  await page.getByRole("option", { name: new RegExp(project.code) }).click();
  const full = page.locator('[data-indicator="full"]');
  await expect(full).toContainText("1 шт.");
  await expect(full).toContainText(/3[\s\u00a0\u202f]000[\s\u00a0\u202f]000/);
});
