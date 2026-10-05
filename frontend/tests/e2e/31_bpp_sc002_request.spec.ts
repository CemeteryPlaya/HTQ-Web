/**
 * SC-002. Создание и согласование заявки (ТЗ §28.2; ранбук, шаг 16).
 *
 * СН: «Заявки» → «Создать заявку», проект (подгружаются статьи группы
 * «Снабжение»), статья (виден остаток), позиции, «Отправить». Ожидается: остаток
 * проверен и зарезервирован, созданы этапы ТД и ОД; после их согласования статус
 * «Утверждена», позиции в Плане закупок СН.
 *
 * Условие (API): проект с утверждённым бюджетом на 10 000 000 ₸ по «Металлопрокату».
 * Решения ТД и ОД — через API (`approveRoute`): это условие второй половины
 * сценария, их экраны «Ждёт меня» проверяет SC-003/SC-005.
 */
import {
  Api, BPP_BASE, approveRoute, articleId, createApprovedBudget, createProject, expect,
  openAs, pick, scenario, test, uniq,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

scenario("SC-002: СН создаёт заявку, ТД и ОД согласуют, позиции попадают в План закупок", async (browser) => {
  const tag = `SC2-${uniq()}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const sn = await Api.as("sn");
  const project = await createProject(fd, pm, tag);
  const metId = await articleId(fd, "E2E-MET");
  await createApprovedBudget(fd, project.id, [{ article_id: metId, limit_amount: "10000000" }]);

  const { page } = await openAs(browser, "sn");
  await page.goto("/bpp/requests");
  await page.getByRole("button", { name: /Создать заявку/ }).or(
    page.getByRole("link", { name: /Создать заявку/ }),
  ).click();
  await expect(page).toHaveURL(/\/bpp\/requests\/new/);

  await pick(page, page.locator("#request-project"), new RegExp(project.code));
  // Подгрузились статьи группы «Снабжение», виден остаток после выбора статьи.
  await pick(page, page.locator("#request-article"), /Металлопрокат/);
  await expect(page.getByRole("region", { name: "Бюджет" })).toContainText(/10[\s\u00a0\u202f]000[\s\u00a0\u202f]000/);

  await page.getByText("ТМЦ", { exact: true }).click();
  const needDate = new Date(Date.now() + 30 * 86_400_000);
  const dd = String(needDate.getDate()).padStart(2, "0");
  const mm = String(needDate.getMonth() + 1).padStart(2, "0");
  await page.locator("#request-need").fill(`${dd}${mm}${needDate.getFullYear()}`);
  await page.locator("#request-justification").fill(
    "Арматура и балки для каркаса здания по проекту, обоснование сценария приёмки",
  );

  const rows: [string, string, string][] = [
    ["Арматура А500 d12", "20", "250000"],
    ["Балка двутавровая 20Б1", "10", "400000"],
  ];
  for (const [i, [name, qty, price]] of rows.entries()) {
    await page.getByRole("button", { name: "Добавить позицию" }).click();
    const row = page.getByTestId("request-item").nth(i);
    await row.getByLabel("Наименование").fill(name);
    await pick(page, row.getByRole("combobox", { name: "Ед." }), /^т$|^шт$/);
    await row.getByLabel("Кол-во").fill(qty);
    await row.getByLabel("Цена").fill(price);
  }
  // 20 × 250 000 + 10 × 400 000 = 9 000 000.
  await expect(page.getByTestId("request-total")).toContainText(/9[\s\u00a0\u202f]000[\s\u00a0\u202f]000/);

  await page.getByRole("button", { name: "Отправить на согласование" }).click();
  await expect(page.getByText("На согласовании", { exact: true }).first()).toBeVisible();
  const url = page.url();
  const requestId = url.match(/requests\/([0-9a-f-]{36})/)?.[1];
  expect(requestId, url).toBeTruthy();

  // Остаток проверен и зарезервирован: в «Задействовано» — сумма заявки.
  const balance = await sn.get(
    `/api/bpp/v1/budgets/balance?project_id=${project.id}&article_id=${metId}`,
  );
  expect(Number(balance.available), JSON.stringify(balance)).toBe(1_000_000);

  // Этапы ТД и ОД (по порядку маршрута «ТД → ОД»).
  await approveRoute(requestId!, ["td", "od"]);

  await page.reload();
  await expect(page.getByText("Утверждена", { exact: true }).first()).toBeVisible();

  // Позиции — в Плане закупок СН.
  await page.goto("/bpp/plan");
  await page.getByRole("combobox", { name: "Проект" }).click();
  await page.getByRole("option", { name: new RegExp(project.code) }).click();
  await expect(page.getByTestId("plan-item")).toHaveCount(2);
  await expect(page.getByText("Арматура А500 d12")).toBeVisible();
});
