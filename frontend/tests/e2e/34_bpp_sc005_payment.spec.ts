/**
 * SC-005. Решение ФД и оплата (ТЗ §28.2; ранбук, шаг 16).
 *
 * ФД: «На решение ФД», отметить счета, «Оплатить». Ожидается: счета у БУХ во
 * вкладке «К оплате»; БУХ по услуге ставит «АВР» и «Запросить документы», автор
 * вкладывает АВР, БУХ принимает и нажимает «Оплачено» (до принятия АВР — E-INV-04).
 *
 * Условия (API): проект с бюджетом, утверждённая заявка СН на услугу, счёт без
 * договора на 3 000 000 ₸ отправлен ФД (его оформление — SC-004).
 */
import {
  Api, BPP_BASE, articleId, attachFile, createApprovedBudget, createApprovedRequest,
  createCounterparty, createProject, createSubmittedInvoice, expect, openAs, pdfFile,
  scenario, test, uniq,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

const MONEY_3M = /3[\s\u00a0\u202f]000[\s\u00a0\u202f]000/;

scenario("SC-005: ФД платит счёт, БУХ отмечает «Оплачено», запрашивает АВР, автор прикладывает, БУХ принимает — «Закрыт»", async (browser) => {
  const tag = `SC5-${uniq()}`;
  const extNumber = `С-${tag}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const sn = await Api.as("sn");
  const project = await createProject(fd, pm, tag);
  const metId = await articleId(fd, "E2E-MET");
  await createApprovedBudget(fd, project.id, [{ article_id: metId, limit_amount: "20000000" }]);
  const counterparty = await createCounterparty(fd, tag);
  await createApprovedRequest(sn, "sn", project.id, metId, [
    { name: "Монтажные работы", qty: "1", price: "3000000" },
  ]);
  const invoice = await createSubmittedInvoice(sn, "sn", project.id, counterparty, {
    amount: "3000000", purchaseType: "works", extNumber,
  });
  expect(invoice.status).toBe("under_review");

  // ── ФД: «На решение ФД» → отметить → «Оплатить» ─────────────────────
  const fdSession = await openAs(browser, "fd");
  const fdPage = fdSession.page;
  await fdPage.goto("/bpp/invoices");
  await fdPage.getByRole("tab", { name: "На решение ФД" }).or(
    fdPage.getByRole("button", { name: "На решение ФД" }),
  ).first().click();
  await fdPage.getByPlaceholder(/Номер, номер счёта контрагента/).fill(extNumber);
  const fdRow = fdPage.getByRole("row").filter({ hasText: invoice.number });
  await expect(fdRow).toHaveCount(1);
  await fdRow.getByRole("checkbox").check();
  await fdPage.getByRole("button", { name: "Оплатить отмеченные" }).click();
  const dialog = fdPage.getByRole("dialog");
  await dialog.getByRole("button", { name: "Оплатить", exact: true }).click();
  await expect(fdRow).toHaveCount(0); // ушёл из очереди ФД

  // ── БУХ: вкладка «К оплате» ─────────────────────────────────────────
  const buhSession = await openAs(browser, "buh");
  const buhPage = buhSession.page;
  await buhPage.goto("/bpp/invoices");
  await buhPage.getByRole("tab", { name: "К оплате" }).or(
    buhPage.getByRole("button", { name: "К оплате" }),
  ).first().click();
  await buhPage.getByPlaceholder(/Номер, номер счёта контрагента/).fill(extNumber);
  await expect(buhPage.getByRole("row").filter({ hasText: invoice.number })).toHaveCount(1);
  await buhPage.goto(`/bpp/invoices/${invoice.id}`);
  await expect(buhPage.getByText("К оплате", { exact: true }).first()).toBeVisible();

  // «Оплачено»: отметка оплаты на полную сумму (дата и сумма предзаполнены).
  await buhPage.getByRole("button", { name: "Оплачено", exact: true }).click();
  const payDialog = buhPage.getByRole("dialog");
  await payDialog.getByLabel(/№ п\/п/).fill("ПП-1");
  await payDialog.getByRole("button", { name: "Оплачено", exact: true }).click();
  await expect(buhPage.getByText("Оплачено", { exact: true }).first()).toBeVisible();

  // Услуга: «Запросить закрывающие» → АВР (D-13: закрывающие запрашивают после оплаты).
  await buhPage.getByRole("button", { name: "Запросить закрывающие" }).click();
  const requestDialog = buhPage.getByRole("dialog");
  await requestDialog.getByLabel("АВР").check();
  await requestDialog.getByLabel("Счёт-фактура").uncheck(); // по ТЗ нужен только АВР
  await requestDialog.getByRole("button", { name: "Запросить закрывающие" }).click();
  await expect(buhPage.getByText("Ждёт закрывающих документов", { exact: true }).first()).toBeVisible();

  // E-INV-04: «Документы предоставлены» без вложенного АВР — отказ (проверка API).
  const early = await sn.postRaw(`/api/bpp/v1/invoices/${invoice.id}/submit-docs`, {});
  expect(early.status, JSON.stringify(early.body)).toBe(422);
  expect(early.body.code).toBe("E-INV-04");

  // ── Автор вкладывает АВР и подтверждает предоставление ──────────────
  const authorSession = await openAs(browser, "sn");
  const authorPage = authorSession.page;
  await authorPage.goto(`/bpp/invoices/${invoice.id}`);
  await attachFile(authorPage, /^АВР$/, pdfFile("avr.pdf"));
  await authorPage.getByRole("button", { name: "Документы предоставлены" }).click();
  await expect(authorPage.getByText("Документы предоставлены", { exact: true }).first()).toBeVisible();

  // ── БУХ принимает документы, затем «Оплачено» ───────────────────────
  await buhPage.reload();
  await buhPage.getByRole("button", { name: "Принять документы" }).click();
  await confirm(buhPage);
  await expect(buhPage.getByText("Закрыт", { exact: true }).first()).toBeVisible();
});

async function confirm(page: import("@playwright/test").Page) {
  const dialog = page.getByRole("alertdialog").or(page.getByRole("dialog")).last();
  await dialog.getByRole("button", { name: /Подтвердить|Да|Принять|ОК/ }).last().click();
}
