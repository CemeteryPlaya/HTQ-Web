/**
 * Страницы «Объекты» и «Субподрядчики» — проход по интерфейсу в браузере.
 *
 * Гонять только против ЛОКАЛЬНОЙ базы (см. шапку 14_sites.spec.ts) и против
 * dev-сервера Vite, а не прод-бандла: сборка для прода падает в headless с
 * "Cannot read properties of undefined (reading 'createContext')" — из-за
 * этого все браузерные тесты в проекте до сих пор помечены test.skip
 * (см. 02_login.spec.ts). В dev-режиме бандл не разбит на vendor-чанки и
 * эта проблема не воспроизводится.
 *
 *   # терминал 1 — стек на локальной БД
 *   docker compose -f docker-compose.yml -f docker-compose.dev.yml \
 *                  -f docker-compose.localdb.yml -f docker-compose.test.yml \
 *                  up -d db redis minio backend-web
 *   # терминал 2 — фронт
 *   cd frontend && npm run dev
 *   # терминал 3 — тесты (порт подставить тот, что занял Vite)
 *   E2E_BASE_URL=http://localhost:3000 npx playwright test 16_ --project=msedge
 *
 * Проверяется то, чего не видит ни один API-тест: что страница вообще
 * смонтирована, что пункт есть в меню, и что форма доводит данные до
 * бэкенда — то есть вся цепочка «клик → запрос → ответ → перерисовка».
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures";

const stamp = () => Date.now() + Math.floor(Math.random() * 1000);

/**
 * Язык прибивается до загрузки приложения.
 *
 * i18next-browser-languagedetector по умолчанию читает локаль браузера, так
 * что без этого спека зависит от машины, на которой её запускают: на
 * английской Windows интерфейс приходит на английском и все селекторы по
 * русскому тексту не находят ничего. Ставим ключ, который детектор читает
 * раньше navigator.
 */
async function pinLanguage(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("i18nextLng", "ru");
  });
}

/** Логин через форму — тот же путь, которым заходит человек. */
async function login(page: import("@playwright/test").Page) {
  await pinLanguage(page);
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

test.describe("Страницы объектов и подрядчиков", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("в меню раздела задач появились Объекты и Субподрядчики", async ({
    page,
  }) => {
    await page.goto("/tasks/sites");
    // По href, а не по подписи: пункт меню не должен пропасть из-за правки
    // перевода, а проверяем мы наличие маршрута.
    const nav = page.locator("aside").first();
    await expect(nav.locator('a[href="/tasks/sites"]')).toBeVisible();
    await expect(nav.locator('a[href="/tasks/contractors"]')).toBeVisible();
    await expect(nav.locator('a[href="/tasks/equipment"]')).toBeVisible();
  });

  test("объект заводится через форму и появляется в таблице", async ({
    page,
  }) => {
    const name = `UI объект ${stamp()}`;
    await page.goto("/tasks/sites");
    await expect(
      page.getByRole("heading", { name: "Объекты" }).first(),
    ).toBeVisible();

    await page.getByRole("button", { name: "Добавить" }).first().click();
    await page.getByRole("dialog").waitFor();
    await page
      .getByRole("dialog")
      .locator("input")
      .first()
      .fill(name);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Добавить" })
      .click();

    // Таблица перерисовалась — значит запрос дошёл и инвалидация сработала.
    await expect(page.getByText(name)).toBeVisible({ timeout: 15_000 });
  });

  test("страница подрядчиков открывается и просит выбрать организацию", async ({
    page,
  }) => {
    await page.goto("/tasks/contractors");
    await expect(
      page.getByRole("heading", { name: "Субподрядчики" }).first(),
    ).toBeVisible();
    // Мастер-деталь: пока никто не выбран, правая часть подсказывает, что делать.
    await expect(page.getByText(/Выберите подрядчика слева/)).toBeVisible();
  });

  test("подрядчик заводится и открывается его карточка", async ({ page }) => {
    const name = `UI ТОО ${stamp()}`;
    await page.goto("/tasks/contractors");
    await page.getByRole("button", { name: "Новый подрядчик" }).click();

    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await dialog.locator("input").first().fill(name);
    await dialog.getByRole("button", { name: "Добавить" }).click();

    // Появился в списке слева...
    const row = page.getByRole("button").filter({ hasText: name });
    await expect(row).toBeVisible({ timeout: 15_000 });

    // ...и по клику раскрывается деталь с блоками людей и привлечений.
    // Именно заголовки блоков: слово «Сотрудники» встречается ещё в шапке
    // сайта и в пустом состоянии, и getByText поймал бы все три.
    await row.click();
    await expect(
      page.getByRole("heading", { name: /^Сотрудники \(/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^Привлечения \(/ }),
    ).toBeVisible();
    // Подсказка про уровни — то, что объясняет пользователю, почему права
    // пока не работают.
    await expect(page.getByText(/права заработают, когда включим вход/)).toBeVisible();
  });

  test("в справочнике техники появилась колонка владельца", async ({
    page,
  }) => {
    await page.goto("/tasks/equipment");
    await expect(
      page.getByRole("heading", { name: "Техника" }).first(),
    ).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Владелец" }))
      .toBeVisible();
    // Тумблер отключённой техники — то, чего раньше не было и из-за чего
    // «удалённая» единица исчезала навсегда.
    await expect(page.getByText("Показать отключённые")).toBeVisible();
  });

  test("в отчётах появилась вкладка «Объекты»", async ({ page }) => {
    await page.goto("/tasks/reports");
    await expect(page.getByRole("tab", { name: "Объекты" })).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("tab", { name: "Объекты" }).click();
    await expect(page.getByText("Задачи по объектам")).toBeVisible();
    await expect(page.getByText("Задачи по проектам")).toBeVisible();
  });
});
