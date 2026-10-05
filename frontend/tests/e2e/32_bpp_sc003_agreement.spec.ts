/**
 * SC-003. Договор из Плана закупок (ТЗ §28.2; ранбук, шаг 16).
 *
 * ПМ: отметить позиции одного проекта и статьи, «Оформить договор»; контрагент
 * (подставляются БИН, страна, ставка НДС), номер, дата, наименование, тип, сумма,
 * файл, «Отправить». Ожидается: ФД, ТД, ОД согласуют, затем ГД; договор
 * «Действует», виден в реестре договоров.
 *
 * Условия (API): проект с бюджетом на проектную статью, контрагент с меткой
 * «Проверенный», утверждённая заявка ПМ (её позиции — в Плане закупок ПМ).
 * Решения ФД → ТД → ОД → ГД — через API (`approveRoute`).
 */
import {
  Api, BPP_BASE, approveRoute, articleId, attachFile, createApprovedBudget,
  createApprovedRequest, createCounterparty, createProject, expect, openAs, pdfFile,
  scenario, test, uniq,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

scenario("SC-003: ПМ оформляет договор из Плана закупок, цепочка ФД→ТД→ОД→ГД, договор «Действует»", async (browser) => {
  const tag = `SC3-${uniq()}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const project = await createProject(fd, pm, tag);
  const desId = await articleId(fd, "E2E-DES");
  await createApprovedBudget(fd, project.id, [{ article_id: desId, limit_amount: "5000000" }]);
  const counterparty = await createCounterparty(fd, tag);
  await createApprovedRequest(pm, "pm", project.id, desId, [
    { name: "Разработка рабочей документации", qty: "1", price: "1200000" },
    { name: "Авторский надзор", qty: "1", price: "800000" },
  ]);

  const { page } = await openAs(browser, "pm");
  await page.goto("/bpp/plan");
  await page.getByRole("combobox", { name: "Проект" }).click();
  await page.getByRole("option", { name: new RegExp(project.code) }).click();
  await expect(page.getByTestId("plan-item")).toHaveCount(2);
  for (const box of await page.getByTestId("plan-item").getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "Оформить договор" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page).toHaveURL(/\/bpp\/agreements\/[0-9a-f-]{36}/);
  const agreementId = page.url().match(/agreements\/([0-9a-f-]{36})/)![1];

  // Контрагент: поиск по наименованию, подставляются БИН и признак плательщика НДС.
  await page.locator("#agr-counterparty").click();
  await page.locator("#agr-counterparty").fill(counterparty.name);
  await page.getByRole("button", { name: new RegExp(counterparty.bin) }).click();
  await expect(page.locator("#agr-counterparty")).toHaveValue(new RegExp(counterparty.bin));

  await page.locator("#agr-name").fill(`Договор на проектные работы ${tag}`);
  await page.locator("#agr-ext-number").fill(`Д-${tag}`);
  const day = (offset: number) => {
    const d = new Date(Date.now() + offset * 86_400_000);
    return `${String(d.getDate()).padStart(2, "0")}${String(d.getMonth() + 1).padStart(2, "0")}${d.getFullYear()}`;
  };
  await page.locator("#agr-ext-date").fill(day(0));
  await page.locator("#agr-valid-to").fill(day(180));
  await page.getByText("Работы и услуги", { exact: true }).click();
  await page.locator("#agr-amount").fill("2000000");
  await page.locator("#agr-amount").blur();

  await attachFile(page, /^Договор$/, pdfFile("dogovor.pdf"));
  await page.getByRole("button", { name: "Отправить на согласование" }).click();
  await expect(page.getByText("На согласовании", { exact: true }).first()).toBeVisible();

  // ФД → ТД → ОД, затем ГД (BR-035).
  await approveRoute(agreementId, ["fd", "td", "od", "gd"]);

  await page.reload();
  await expect(page.getByText("Действует", { exact: true }).first()).toBeVisible();

  // Виден в реестре договоров.
  await page.goto("/bpp/agreements");
  await expect(page.getByText(`Д-${tag}`).first()).toBeVisible();
});
