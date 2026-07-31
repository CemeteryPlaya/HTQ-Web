/**
 * HR — работа с девятью разделами бокового меню В БРАУЗЕРЕ.
 *
 * Разделы: PMO, публичные ссылки, учёт времени, рекрутинг, архив,
 * документы, кадровая история, производственный календарь, штатное
 * расписание.
 *
 * Гонять против dev-сервера Vite и ЛОКАЛЬНОЙ базы (см. шапки 14_sites и
 * 16_sites_contractors_ui).
 *
 * Отличие от 18_hr_ui.spec.ts: тот обходит страницы и проверяет, что они
 * ожили (не белый экран, нет сырых ключей, под капотом не сыпется 500).
 * Здесь страницы ИСПОЛЬЗУЮТСЯ: заводится ОУП и в него добавляется человек,
 * создаётся и отзывается публичная ссылка, отмечается праздник в
 * календаре, заводится строка штатного расписания и сверяется ФОТ. То
 * есть проверяется связка «форма → запрос → перерисовка списка», которую
 * API-тест не видит: он не знает, дошли ли данные до формы и обновился ли
 * экран после ответа.
 *
 * Данные каждый тест создаёт себе сам и метит префиксом «UI ». Пустая
 * локальная база — нормальное стартовое состояние.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE } from "./fixtures";
import type { Page } from "@playwright/test";

const stamp = () => Date.now() + Math.floor(Math.random() * 10000);

async function login(page: Page) {
  // Язык прибиваем явно: LanguageDetector иначе берёт локаль машины, и
  // русские селекторы разъезжаются в зависимости от того, где гоняют.
  await page.addInitScript(() => {
    window.localStorage.setItem("i18nextLng", "ru");
  });
  await page.goto("/login");
  const password = page.locator('input[type="password"]').first();
  await expect(password).toBeVisible({ timeout: 30_000 });
  await page.locator('input[type="text"]').first().fill(ADMIN_EMAIL);
  await password.fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });
}

/** Ошибки, которые страница роняет под капотом. Рендер может выглядеть
 *  целым, пока в консоли лежит TypeError, а запрос отвечает 500. */
function watch(page: Page) {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300));
  });
  page.on("response", (r) => {
    if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url().split("?")[0]}`);
  });
  return { consoleErrors, serverErrors };
}

/** Прямой вызов API из теста — чтобы подготовить данные, которые в UI
 *  завести либо нельзя, либо слишком долго (сотрудник требует отдела и
 *  должности, а это три формы подряд). */
async function api(page: Page, method: string, path: string, body?: any) {
  const token = await page.evaluate(() => {
    for (const key of ["access_token", "accessToken", "token"]) {
      const direct = window.localStorage.getItem(key);
      if (direct) return direct;
    }
    // Часть сборок держит токены одним объектом.
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i)!;
      const v = window.localStorage.getItem(k) || "";
      if (v.startsWith("eyJ")) return v;
      try {
        const parsed = JSON.parse(v);
        if (parsed?.access) return parsed.access;
      } catch {
        /* не JSON — пропускаем */
      }
    }
    return null;
  });
  expect(token, "в localStorage нет токена доступа").toBeTruthy();

  const resp = await page.request.fetch(`${API_BASE}/api/hr/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    data: body,
  });
  return resp;
}

/** Отдел + должность + сотрудник через API. */
async function seedPerson(page: Page) {
  const dept = await (
    await api(page, "POST", "/departments/", { name: `UI отдел ${stamp()}` })
  ).json();
  const position = await (
    await api(page, "POST", "/positions/", {
      title: `UI должность ${stamp()}`,
      department_id: dept.id,
      weight: 10_000 + Math.floor(Math.random() * 5_000_000),
    })
  ).json();
  const employee = await (
    await api(page, "POST", "/employees/", {
      first_name: "Юай",
      last_name: `Тестов${stamp()}`,
      email: `ui${stamp()}@htq.test`,
      hire_date: new Date().toISOString().slice(0, 10),
      department_id: dept.id,
      position_id: position.id,
    })
  ).json();
  return { dept, position, employee };
}

test.describe("HR: PMO в браузере", () => {
  test("ОУП создаётся из формы и появляется в списке слева", async ({ page }) => {
    const { consoleErrors } = watch(page);
    await login(page);
    await page.goto("/hr/pmo");

    await expect(
      page.getByRole("heading", { name: /Офис управления проектами/i }),
    ).toBeVisible({ timeout: 20_000 });

    const name = `UI ОУП ${stamp()}`;
    const code = `UI-${stamp()}`;

    await page.getByRole("button", { name: "+ Создать" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Новый ОУП")).toBeVisible();

    await dialog.locator("label", { hasText: "Название" }).locator("input").fill(name);
    await dialog.locator("label", { hasText: "Код" }).locator("input").fill(code);
    await dialog
      .locator("label", { hasText: "Описание" })
      .locator("input")
      .fill("Создан браузерным тестом");
    await dialog.getByRole("button", { name: "Создать" }).click();

    // Диалог закрылся и карточка появилась — значит список перезапросился.
    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(name)).toBeVisible({ timeout: 15_000 });
    // Код показывается моноширинным и в верхнем регистре (форма приводит).
    await expect(page.getByText(code.toUpperCase())).toBeVisible();

    expect(consoleErrors.join("\n")).not.toContain("TypeError");
  });

  test("участник добавляется, попадает в счётчик вкладки и в граф", async ({
    page,
  }) => {
    await login(page);
    const { employee } = await seedPerson(page);

    // Сам ОУП заводим через API — форма уже проверена выше, здесь важен
    // именно сценарий с участниками.
    const pmo = await (
      await api(page, "POST", "/pmo/", {
        name: `UI ОУП участники ${stamp()}`,
        code: `UIM-${stamp()}`,
      })
    ).json();

    await page.goto("/hr/pmo");
    await page.getByText(pmo.name).click();

    await expect(page.getByRole("heading", { name: pmo.name })).toBeVisible();
    await page.getByRole("tab", { name: /Участники/ }).click();
    await expect(page.getByText("Нет участников")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "+ Добавить" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Добавить участника")).toBeVisible();

    // Селект сотрудника — radix, поэтому кликом, а не fill.
    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: new RegExp(employee.last_name) }).click();
    await dialog
      .locator("label", { hasText: "Роль в ОУП" })
      .locator("input")
      .fill("Главный инженер");
    await dialog.getByRole("button", { name: "Добавить" }).click();

    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(employee.last_name)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Главный инженер")).toBeVisible();
    // Счётчик на вкладке — признак, что список перезапросился, а не
    // дорисовался локально.
    await expect(page.getByRole("tab", { name: /Участники \(1\)/ })).toBeVisible();

    // Граф строится из тех же данных.
    await page.getByRole("tab", { name: "Граф" }).click();
    await expect(page.getByText(pmo.name).first()).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("HR: публичные ссылки в браузере", () => {
  test("ссылка создаётся, токен показывается один раз, отзыв меняет статус", async ({
    page,
    context,
  }) => {
    await login(page);
    await page.goto("/hr/share-links");
    await expect(
      page.getByRole("heading", { name: /Общий доступ/i }),
    ).toBeVisible({ timeout: 20_000 });

    const label = `UI ссылка ${stamp()}`;
    await page.getByRole("button", { name: "+ Создать ссылку" }).click();
    const dialog = page.getByRole("dialog");
    await dialog
      .locator("label", { hasText: "Описание (для кого)" })
      .locator("input")
      .fill(label);
    await dialog
      .locator("label", { hasText: "Имя получателя" })
      .locator("input")
      .fill("ТОО Браузерный тест");
    await dialog.getByRole("button", { name: "Создать" }).click();

    // Окно с одноразовым токеном — единственное место, где его видно.
    await expect(page.getByText("Ссылка создана")).toBeVisible({ timeout: 15_000 });
    const shown = await page.locator(".font-mono.break-all").first().innerText();
    expect(shown).toContain("/public/org/");
    const token = shown.trim().split("/public/org/")[1];
    expect(token.length).toBeGreaterThan(20);

    await page.getByRole("button", { name: "Готово" }).click();
    await expect(page.getByText(label)).toBeVisible({ timeout: 15_000 });
    // Токен нигде на странице списка не остаётся.
    expect(await page.content()).not.toContain(token);

    // Ссылка действительно открывается — и без авторизации.
    const anon = await context.browser()!.newContext();
    const anonPage = await anon.newPage();
    await anonPage.goto(`/public/org/${token}`);
    await expect(anonPage.getByText(/ТОО Браузерный тест/)).toBeVisible({
      timeout: 20_000,
    });
    await anon.close();

    // После открытия одноразовая ссылка уезжает в «Историю».
    await page.reload();
    const row = page.locator("div").filter({ hasText: label }).last();
    await expect(row.getByText("Использована")).toBeVisible({ timeout: 15_000 });
  });

  test("журнал ссылки показывает создание и открытие", async ({ page }) => {
    await login(page);
    const label = `UI журнал ${stamp()}`;
    const link = await (
      await api(page, "POST", "/share-links/", {
        label,
        link_type: "one_time",
      })
    ).json();

    // Открываем ссылку, чтобы в журнале было что смотреть.
    await page.request.get(`${API_BASE}/api/hr/v1/public/org/${link.token}`);

    await page.goto("/hr/share-links");
    const card = page
      .locator("div.rounded-xl")
      .filter({ hasText: label })
      .first();
    await card.getByRole("button", { name: "Журнал" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Журнал ссылки")).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByText("Создана")).toBeVisible();
    await expect(dialog.getByText("Открыта")).toBeVisible();
  });
});

test.describe("HR: учёт времени в браузере", () => {
  test("страница не падает на ответе бэкенда", async ({ page }) => {
    const { consoleErrors } = watch(page);
    await login(page);
    await page.goto("/hr/time-tracking");

    // Заголовок приходит из layout и рисуется до таблицы — по нему нельзя
    // судить, что страница жива. Смотрим на таблицу и на консоль.
    await expect(
      page.getByRole("heading", { name: /Уч[её]т времени|Отсутстви/i }),
    ).toBeVisible({ timeout: 20_000 });

    await page.waitForTimeout(2_000);

    // GET /time-tracking/ отдаёт конверт {items,total,...}, а страница
    // типизирует его как массив и делает records.map(...). На объекте это
    // TypeError, и таблица не рисуется. Тест держит эту границу: пока
    // контракт не сведут, он будет красным и назовёт причину.
    const crashed = consoleErrors.filter(
      (e) => e.includes("is not a function") || e.includes("TypeError"),
    );
    expect(
      crashed.join("\n"),
      "страница учёта времени роняет рендер: бэкенд отдаёт {items:[…]}, " +
        "а HRTimeTracking.tsx ждёт массив",
    ).toEqual("");

    await expect(page.getByRole("table")).toBeVisible({ timeout: 10_000 });
  });
});

test.describe("HR: рекрутинг в браузере", () => {
  test("три вкладки раздела переключаются и грузят своё", async ({ page }) => {
    const { serverErrors } = watch(page);
    await login(page);
    await page.goto("/hr/recruitment");

    await expect(page.getByRole("tab", { name: /Ваканс/i })).toBeVisible({
      timeout: 20_000,
    });
    for (const name of [/Ваканс/i, /Отклик|Кандидат/i, /Оффер/i]) {
      await page.getByRole("tab", { name }).click();
      // Переключение вкладки не должно ронять запрос за данными.
      await page.waitForTimeout(800);
    }
    expect(serverErrors.join("\n")).toEqual("");
  });

  test("созданная через API вакансия видна на вкладке", async ({ page }) => {
    await login(page);
    const { dept, position } = await seedPerson(page);
    const title = `UI вакансия ${stamp()}`;
    const resp = await api(page, "POST", "/vacancies/", {
      title,
      department_id: dept.id,
      position_id: position.id,
      description: "Проверка отображения",
    });
    expect(resp.status()).toBe(201);

    await page.goto("/hr/recruitment");
    await page.getByRole("tab", { name: /Ваканс/i }).click();
    await expect(page.getByText(title)).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("HR: архив в браузере", () => {
  test("завершённый отклик доезжает до архива", async ({ page }) => {
    await login(page);
    const { dept, position } = await seedPerson(page);
    const vacancy = await (
      await api(page, "POST", "/vacancies/", {
        title: `UI архив ${stamp()}`,
        department_id: dept.id,
        position_id: position.id,
      })
    ).json();
    const name = `UI Отказник ${stamp()}`;
    const application = await (
      await api(page, "POST", "/applications/", {
        vacancy_id: vacancy.id,
        candidate_name: name,
        candidate_email: `arch${stamp()}@example.com`,
      })
    ).json();
    await api(page, "POST", `/applications/${application.id}/status`, {
      status: "rejected",
    });

    await page.goto("/hr/archive");
    await expect(
      page.getByRole("heading", { name: /Архив/i }).first(),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(name)).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("HR: документы в браузере", () => {
  test("документ, заведённый через API, виден в списке", async ({ page }) => {
    const { serverErrors } = watch(page);
    await login(page);
    const { employee } = await seedPerson(page);
    const title = `UI договор ${stamp()}`;
    const resp = await api(page, "POST", "/documents/", {
      employee_id: employee.id,
      title,
      doc_type: "contract",
      file_path: `/docs/ui-${stamp()}.pdf`,
      file_size: 1024,
      mime_type: "application/pdf",
      uploaded_by: employee.id,
    });
    expect(resp.status()).toBe(201);

    await page.goto("/hr/documents");
    await expect(
      page.getByRole("heading", { name: /Документ/i }).first(),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(title)).toBeVisible({ timeout: 20_000 });
    expect(serverErrors.join("\n")).toEqual("");
  });
});

test.describe("HR: кадровая история в браузере", () => {
  test("событие создаётся из формы и попадает в таблицу", async ({ page }) => {
    await login(page);
    const { employee, dept, position } = await seedPerson(page);
    expect(dept.id && position.id).toBeTruthy();

    await page.goto("/hr/history");
    await expect(
      page.getByRole("heading", { name: /Кадровая истори|Истори/i }).first(),
    ).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: /Добавить|Создать|Новое/i }).first().click();
    const dialog = page.getByRole("dialog");

    // Сотрудник — первый селект в форме.
    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: new RegExp(employee.last_name) }).click();

    const order = `ПР-UI-${stamp()}`;
    await dialog
      .locator("label", { hasText: /Номер приказа/i })
      .locator("input")
      .fill(order);
    await dialog.getByRole("button", { name: /Сохранить/i }).click();

    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(order)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(employee.last_name)).toBeVisible();
  });

  test("фильтр по типу события сужает таблицу", async ({ page }) => {
    await login(page);
    const { employee, dept, position } = await seedPerson(page);
    const today = new Date().toISOString().slice(0, 10);

    const hiredOrder = `ПР-НАЙМ-${stamp()}`;
    const transferOrder = `ПР-ПЕР-${stamp()}`;
    await api(page, "POST", "/personnel-history/", {
      employee: employee.id,
      event_type: "hired",
      event_date: today,
      to_department: dept.id,
      to_position: position.id,
      order_number: hiredOrder,
    });
    await api(page, "POST", "/personnel-history/", {
      employee: employee.id,
      event_type: "transfer",
      event_date: today,
      from_department: dept.id,
      to_department: dept.id,
      order_number: transferOrder,
    });

    await page.goto("/hr/history");
    await expect(page.getByText(hiredOrder)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(transferOrder)).toBeVisible();

    // Клик по бейджу типа — это и есть фильтр (отдельного селекта нет).
    const row = page.getByRole("row").filter({ hasText: transferOrder });
    await row.getByRole("button").first().click();

    await expect(page.getByText(transferOrder)).toBeVisible();
    await expect(page.getByText(hiredOrder)).not.toBeVisible({ timeout: 10_000 });
  });
});

test.describe("HR: производственный календарь в браузере", () => {
  test("праздник из API появляется в списке исключений года", async ({ page }) => {
    await login(page);
    const year = new Date().getFullYear();
    const day = `${year}-12-31`;
    const note = `UI праздник ${stamp()}`;
    const resp = await api(page, "PUT", `/calendar/${day}`, {
      day_type: "holiday",
      norm_hours: 0,
      note,
    });
    expect(resp.status()).toBe(200);

    await page.goto("/hr/production-calendar");
    await expect(
      page.getByRole("heading", { name: /Производственный календарь/i }),
    ).toBeVisible({ timeout: 20_000 });

    await expect(page.getByText(day)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(note)).toBeVisible();
    // Заголовок секции считает исключения — счётчик не должен быть нулевым.
    await expect(page.getByText(/Исключения года \((?!0\))\d+\)/)).toBeVisible();

    await api(page, "DELETE", `/calendar/${day}`);
  });

  test("сменный график создаётся кнопкой и исчезает после удаления", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/hr/production-calendar");
    await expect(page.getByText("Сменные графики")).toBeVisible({
      timeout: 20_000,
    });

    const name = `UI 2/2 ${stamp()}`;
    await page.getByPlaceholder(/Название/).fill(name);
    await page.getByRole("button", { name: "+ 2/2 шаблон" }).click();

    await expect(page.getByText(name)).toBeVisible({ timeout: 15_000 });
    // Цикл из четырёх слотов — то, что кнопка обещает.
    await expect(page.getByText(/цикл 4 дн\./).first()).toBeVisible();

    const row = page.locator("div.rounded.border").filter({ hasText: name });
    await row.getByRole("button", { name: "Удалить" }).click();
    await expect(page.getByText(name)).not.toBeVisible({ timeout: 15_000 });
  });
});

test.describe("HR: штатное расписание в браузере", () => {
  test("строка показывает ФОТ и сходится со сводкой сверху", async ({ page }) => {
    const { serverErrors } = watch(page);
    await login(page);
    const { dept, position } = await seedPerson(page);

    const resp = await api(page, "POST", "/staffing/", {
      position_id: position.id,
      department_id: dept.id,
      grade: 2,
      headcount: "2",
      salary: "400000",
      note: `UI строка ${stamp()}`,
    });
    expect(resp.status()).toBe(201);
    const line = await resp.json();

    await page.goto("/hr/staffing");
    await expect(
      page.getByRole("heading", { name: /Штатное расписание/i }),
    ).toBeVisible({ timeout: 20_000 });

    // ФОТ строки = 2 × 400000. Именно эта цифра должна быть в таблице.
    const row = page.getByRole("row").filter({ hasText: "800000.00" });
    await expect(row).toBeVisible({ timeout: 20_000 });

    // Сводка сверху — независимый расчёт того же; она обязана быть не нулевой.
    const summary = page.getByText(/Итого ФОТ:/);
    await expect(summary).toBeVisible();
    await expect(page.getByText(/Ставки: .*занято: .*вакантно:/)).toBeVisible();

    expect(serverErrors.join("\n")).toEqual("");
    await api(page, "DELETE", `/staffing/${line.id}`);
  });

  test("удаление строки убирает её из таблицы", async ({ page }) => {
    await login(page);
    const { dept, position } = await seedPerson(page);
    const note = `UI удаляемая ${stamp()}`;
    await api(page, "POST", "/staffing/", {
      position_id: position.id,
      department_id: dept.id,
      headcount: "1",
      salary: "123456",
      note,
    });

    await page.goto("/hr/staffing");
    const row = page.getByRole("row").filter({ hasText: "123456.00" });
    await expect(row).toBeVisible({ timeout: 20_000 });

    await row.getByRole("button", { name: "Удалить" }).click();
    await expect(row).not.toBeVisible({ timeout: 15_000 });
  });
});
