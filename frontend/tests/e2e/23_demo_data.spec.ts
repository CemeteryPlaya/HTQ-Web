/**
 * Демо-данные домена задач и права рядового сотрудника.
 *
 * Гонять против ЛОКАЛЬНОЙ базы, наполненной командами:
 *   manage.py seed_hr_demo
 *   manage.py seed_employee_accounts     # без них у задач нет исполнителей
 *   manage.py seed_tasks_demo
 *
 * Спека НИЧЕГО не создаёт и не удаляет — только читает засеянное. Поэтому
 * её можно гонять сколько угодно раз, не засоряя справочники.
 *
 * Вторая половина спеки закрывает дыру, которая держалась всё это время: до
 * появления учёток сотрудников в базе не существовало ни одного
 * НЕ-администратора, и ветку «рядовой сотрудник» нечем было проверить —
 * гейты маршрутов и меню принимались на веру.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE } from "./fixtures";
import type { Page } from "@playwright/test";

const API = `${API_BASE}/api/tasks/v1`;

/** Засеянная учётка рядового сотрудника (manage.py seed_employee_accounts). */
const EMPLOYEE_EMAIL = process.env.E2E_EMPLOYEE_EMAIL || "abdrahmanov.e@htq.kz";
const EMPLOYEE_PASSWORD = process.env.E2E_EMPLOYEE_PASSWORD || "demo12345";

async function login(page: Page, email: string, password: string) {
  await page.addInitScript(() => {
    window.localStorage.setItem("i18nextLng", "ru");
  });
  await page.goto("/login");
  const passwordInput = page.locator('input[type="password"]').first();
  await expect(passwordInput).toBeVisible({ timeout: 30_000 });
  await page.locator('input[type="text"]').first().fill(email);
  await passwordInput.fill(password);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });
}

const auth = (token: string) => ({ headers: { Authorization: `Bearer ${token}` } });

test.describe("Демо-данные: домен задач наполнен связно", () => {
  test("у каждого проекта есть объекты и ровно один основной", async ({
    request,
    adminTokens,
  }) => {
    const projects = await (
      await request.get(`${API}/projects/`, auth(adminTokens.access))
    ).json();
    expect(projects.length).toBeGreaterThanOrEqual(4);

    for (const project of projects) {
      expect(project.sites.length, `у проекта «${project.name}» нет объектов`)
        .toBeGreaterThan(0);
      const primary = project.sites.filter((s: { is_primary: boolean }) => s.is_primary);
      expect(primary.length, `основных объектов у «${project.name}»`).toBe(1);
    }
  });

  test("проекты знают своего владельца и отдел", async ({
    request,
    adminTokens,
  }) => {
    // Владелец — это user_id платформенной учётки. Пока учёток у
    // сотрудников не было, тут везде стоял null и отчёты по людям пустовали.
    const projects = await (
      await request.get(`${API}/projects/`, auth(adminTokens.access))
    ).json();
    for (const project of projects) {
      expect(project.owner_name, `владелец «${project.name}»`).toBeTruthy();
      expect(project.department_name, `отдел «${project.name}»`).toBeTruthy();
    }
  });

  test("статистика даёт непустые разрезы по проектам и объектам", async ({
    request,
    adminTokens,
  }) => {
    const stats = await (
      await request.get(`${API}/tasks/stats/`, auth(adminTokens.access))
    ).json();

    // Ровно то, ради чего заводились объекты: разрезы перестают быть пустыми.
    expect(stats.by_project.length).toBeGreaterThanOrEqual(4);
    expect(stats.by_site.length).toBeGreaterThanOrEqual(4);

    // Все семь статусов представлены — иначе доску и диаграммы не на чем
    // смотреть глазами.
    expect(Object.keys(stats.by_status).sort()).toEqual([
      "backlog", "blocked", "cancelled", "done",
      "in_progress", "in_review", "todo",
    ]);
  });

  test("партнёры: три уровня людей и привлечения по объектам", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const contractors = await (await request.get(`${API}/contractors/`, ctx)).json();
    expect(contractors.length).toBeGreaterThanOrEqual(4);

    const levels = new Set<string>();
    for (const contractor of contractors) {
      const workers = await (
        await request.get(`${API}/contractors/${contractor.id}/workers/`, ctx)
      ).json();
      for (const worker of workers) levels.add(worker.level);
    }

    // Уровень — свойство человека, и все три должны быть в наличии:
    // на них держится будущая матрица прав партнёров.
    expect([...levels].sort()).toEqual(["junior", "middle", "senior"]);

    // Привлечения лежат отдельной коллекцией, не под партнёром.
    const engagements = await (
      await request.get(`${API}/contractor-engagements/`, ctx)
    ).json();
    expect(engagements.length).toBeGreaterThanOrEqual(5);
    // Пара «организация + объект» — та единица, в которой сформулировано
    // будущее право senior видеть задачи своей организации по объекту.
    expect(engagements.some((e: { site_id: number | null }) => e.site_id != null))
      .toBe(true);
  });

  test("техника партнёра всегда называет владельца", async ({
    request,
    adminTokens,
  }) => {
    const equipment = await (
      await request.get(`${API}/equipment/`, auth(adminTokens.access))
    ).json();
    expect(equipment.length).toBeGreaterThanOrEqual(6);

    for (const item of equipment) {
      if (item.ownership === "contractor") {
        expect(item.contractor_id, `«${item.name}» без организации`).toBeTruthy();
      } else {
        expect(item.contractor_id, `у «${item.name}» лишняя организация`).toBeFalsy();
      }
    }
  });

  test("объект задачи всегда входит в объекты её проекта", async ({
    request,
    adminTokens,
  }) => {
    // Тот же инвариант, что стережёт resolve_task_site на запись. Данные,
    // созданные в обход API, обязаны ему подчиняться — иначе в базе есть
    // строки, которые через форму завести было бы нельзя.
    const ctx = auth(adminTokens.access);
    const projects = await (await request.get(`${API}/projects/`, ctx)).json();
    for (const project of projects) {
      const allowed = new Set<number>(project.site_ids);
      const tasks = await (
        await request.get(`${API}/projects/${project.id}/tasks/`, ctx)
      ).json();
      for (const task of tasks) {
        if (task.site_id != null) {
          expect(allowed.has(task.site_id),
            `задача ${task.key}: объект вне проекта «${project.name}»`).toBe(true);
        }
      }
    }
  });
});

test.describe("Демо-данные в браузере", () => {
  test("страница проектов показывает засеянное без предупреждений", async ({
    page,
  }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto("/manage/projects");

    await expect(page.getByText("Алга-2026: подстанция 110/10")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Сазаган: СЭС, вторая очередь")).toBeVisible();

    // У всех засеянных проектов объекты заданы, значит плашки-предупреждения
    // быть не должно ни на одной карточке.
    await expect(page.getByText("Объекты не заданы")).toHaveCount(0);

    // Чип основного объекта со звездой.
    await expect(page.getByText("★ Алга").first()).toBeVisible();
  });

  test("партнёры и их люди видны на своей странице", async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto("/tasks/contractors");
    await expect(page.getByText("ТОО «Алга-Строй-Монтаж»")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("ТОО «ЭлектроМонтажСервис»")).toBeVisible();
  });
});

test.describe("Права рядового сотрудника", () => {
  test("на страницу проектов его не пускают", async ({ page }) => {
    await login(page, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD);
    await page.goto("/manage/projects");

    // Гейт маршрута отправляет на профиль, а не оставляет белый экран.
    await page.waitForURL(/\/myprofile/, { timeout: 20_000 });
    await expect(page.getByText("Алга-2026: подстанция 110/10")).toHaveCount(0);
  });

  test("управленческие страницы задач тоже закрыты", async ({ page }) => {
    await login(page, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD);
    for (const path of ["/tasks/reports", "/tasks/sites", "/tasks/contractors"]) {
      await page.goto(path);
      await page.waitForURL(/\/myprofile/, { timeout: 20_000 });
    }
  });

  test("а свои задачи открываются", async ({ page }) => {
    await login(page, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD);
    await page.goto("/tasks");
    // Раздел задач рядовому доступен — он там ведёт свою работу.
    await expect(page).toHaveURL(/\/tasks/);
    await expect(page.getByText(/Задачи|Мои задачи/i).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("в меню нет пунктов, которые всё равно выкинут", async ({ page }) => {
    await login(page, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD);
    await page.goto("/myprofile");
    await expect(page.getByRole("link", { name: "Задачи" }).first())
      .toBeVisible({ timeout: 20_000 });

    // Проверяем по АДРЕСАМ, а не по подписям: в шапке публичного сайта есть
    // свой пункт «Проекты» (/projects — портфолио), он виден всем и к
    // рабочим проектам отношения не имеет. Подпись поймала бы его и
    // объявила дырой то, что дырой не является.
    for (const href of ["/manage/projects", "/tasks/reports", "/tasks/roadmap"]) {
      await expect(
        page.locator(`a[href="${href}"]`),
        `меню не должно рекламировать ${href} — маршрут всё равно выкинет`,
      ).toHaveCount(0);
    }
    // А задачи в меню быть обязаны: рядовой там работает.
    await expect(page.locator('a[href="/tasks"]')).not.toHaveCount(0);
  });
});
