/**
 * SC-001. Утверждение бюджета (ТЗ §28.2; ранбук, шаг 16).
 *
 * ФД: «Бюджеты» → «Создать бюджет», проект, строки статей и лимиты, итоги
 * пересчитались, «Утвердить». Ожидается: версия 1, статьи доступны для заявок
 * (BR-001, BR-002).
 *
 * Условие (через API): проект с руководителем ПМ — заводит АДМ/ФД в «Проектах»,
 * это не часть сценария бюджета. Всё остальное — через экраны.
 */
import {
  Api, BPP_BASE, USERS, createProject, expect, openAs, pick, test, uniq,
  confirmDialog, articleId, scenario,
} from "./bpp_fixtures";

test.use({ baseURL: BPP_BASE });

scenario("SC-001: ФД создаёт и утверждает бюджет проекта", async (browser) => {
  const tag = `SC1-${uniq()}`;
  const fd = await Api.as("fd");
  const pm = await Api.as("pm");
  const project = await createProject(fd, pm, tag);
  const metId = await articleId(fd, "E2E-MET");

  const { page } = await openAs(browser, "fd");
  {
    await page.goto("/bpp/budgets");
    await page.getByRole("button", { name: "Создать бюджет" }).or(
      page.getByRole("link", { name: "Создать бюджет" }),
    ).click();
    await expect(page).toHaveURL(/\/bpp\/budgets\/new/);

    // Проект
    await pick(page, page.locator("#budget-project"), new RegExp(project.code));

    // Строки статей и лимиты: две статьи группы «Снабжение» и одна проектная.
    const lines: [string, string][] = [
      ["Металлопрокат", "10000000"],
      ["Электрооборудование", "2500000"],
      ["Проектные работы", "1500000"],
    ];
    for (const [i, [article, limit]] of lines.entries()) {
      await page.getByRole("button", { name: "Добавить статью" }).click();
      const row = page.getByTestId("budget-line").nth(i);
      await pick(page, row.getByRole("combobox", { name: "Статья бюджета" }), new RegExp(article));
      await row.getByLabel("Лимит").fill(limit);
    }

    // Итоги пересчитались на лету: 10 000 000 + 2 500 000 + 1 500 000 = 14 000 000.
    const footer = page.locator("tfoot");
    await expect(footer).toContainText(/14[\s\u00a0\u202f]000[\s\u00a0\u202f]000/);

    // Черновик сначала сохраняется (кнопка «Утвердить» появляется у сохранённого).
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page).toHaveURL(/\/bpp\/budgets\/(?!new)[0-9a-f-]{36}/);
    await page.getByRole("button", { name: "Утвердить", exact: true }).click();
    await confirmDialog(page);

    // После утверждения — версия 1, «Утверждён», карточка только для чтения
    // («Корректировать» вместо «Утвердить»).
    await expect(page.getByRole("button", { name: "Корректировать" })).toBeVisible();
    await expect(page.getByText("Утверждён", { exact: true }).first()).toBeVisible();
    // Вкладка «Версии»: версия 1 — «Действующая».
    await page.getByRole("tab", { name: "Версии" }).click();
    const versionRow = page.getByRole("row").filter({ hasText: "Действующая" });
    await expect(versionRow).toHaveCount(1);
    await expect(versionRow.getByRole("cell").first()).toHaveText("1");
  }

  // BR-001/BR-002: статья утверждённого бюджета доступна для заявок — СН
  // видит остаток статьи (то, что подгружает форма заявки): лимит, ничего не
  // задействовано.
  const sn = await Api.as("sn");
  const balance = await sn.get(
    `/api/bpp/v1/budgets/balance?project_id=${project.id}&article_id=${metId}`,
  );
  expect(Number(balance.available), JSON.stringify(balance)).toBe(10_000_000);
  const budgets = await fd.get(`/api/bpp/v1/budgets?project_id=${project.id}`);
  const card = (budgets.items ?? budgets)[0];
  expect(card.status).toBe("approved");
  expect(card.version_no).toBe(1);
});
