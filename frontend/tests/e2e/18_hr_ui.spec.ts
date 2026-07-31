/**
 * HR — обход всех страниц раздела в браузере.
 *
 * Гонять против dev-сервера Vite и ЛОКАЛЬНОЙ базы (см. шапки 14_sites и
 * 16_sites_contractors_ui).
 *
 * Задача этой спеки — не проверить бизнес-логику (её держат юнит-тесты и
 * 17_hr_api), а поймать то, что видит только браузер: белый экран, упавший
 * рендер, необработанную ошибку загрузки, сырой ключ перевода вместо
 * подписи. Такие поломки не ловит ни один API-тест, потому что API при этом
 * отвечает 200.
 *
 * На каждой странице собираются ошибки консоли и неудачные запросы: если
 * страница отрисовалась, но под ней сыпется 500, тест это назовёт.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures";
import type { Page } from "@playwright/test";

/** Страницы раздела и то, по чему видно, что страница действительно ожила. */
const HR_PAGES: { path: string; marker: RegExp }[] = [
  { path: "/hr/employees", marker: /Сотрудники|Employees/i },
  { path: "/hr/departments", marker: /Отдел|Department|Структур/i },
  { path: "/hr/positions", marker: /Должност|Position/i },
  { path: "/hr/org-chart", marker: /Оргструктур|Org|Схем/i },
  { path: "/hr/staffing", marker: /Штат|Staffing/i },
  // «Уч[её]т» — на странице пишут без ё, в других местах с ней.
  { path: "/hr/time-tracking", marker: /Уч[её]т времени|Отсутстви|Табел/i },
  { path: "/hr/recruitment", marker: /Подбор|Recruit|Ваканс/i },
  { path: "/hr/vacancies", marker: /Ваканс|Vacanc/i },
  { path: "/hr/applications", marker: /Отклик|Application|Кандидат/i },
  { path: "/hr/offers", marker: /Оффер|Offer/i },
  { path: "/hr/documents", marker: /Документ|Document/i },
  { path: "/hr/history", marker: /Истори|History/i },
  { path: "/hr/logs", marker: /Журнал|Log/i },
  { path: "/hr/archive", marker: /Архив|Archive/i },
  { path: "/hr/accounts", marker: /Учётн|Account|Профил/i },
  { path: "/hr/pmo", marker: /PMO/i },
  { path: "/hr/share-links", marker: /ссылк|link/i },
  { path: "/hr/production-calendar", marker: /Календар|Calendar/i },
  { path: "/admin/levels", marker: /Уровн|Level/i },
  { path: "/admin/access-levels", marker: /Уровн|Level|Доступ/i },
];

async function pinLanguage(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("i18nextLng", "ru");
  });
}

async function login(page: Page) {
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

/** Собирает то, что страница уронила под капотом. */
function watch(page: Page) {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200));
  });
  page.on("response", (resp) => {
    if (resp.status() >= 500) {
      serverErrors.push(`${resp.status()} ${resp.url().split("?")[0]}`);
    }
  });
  return { consoleErrors, serverErrors };
}

test.describe("HR: обход всех страниц раздела", () => {
  for (const { path, marker } of HR_PAGES) {
    test(`${path} открывается и живёт`, async ({ page }) => {
      const { consoleErrors, serverErrors } = watch(page);
      await login(page);
      await page.goto(path);

      // 1. Страница смонтирована: под шапкой есть содержимое, а не пустота.
      //    Именно белый экран — типичный симптом упавшего рендера.
      const main = page.locator("main").first();
      await expect(main).toBeVisible({ timeout: 20_000 });
      await expect(main).not.toBeEmpty();

      // 2. Нас не выкинуло ролевым гейтом обратно в профиль.
      expect(page.url(), `${path} отбросил на другую страницу`).toContain(path);

      // 3. На странице есть что-то узнаваемое по смыслу, а не только каркас.
      await expect(main).toContainText(marker, { timeout: 20_000 });

      // 4. Ни одного 500 под капотом. Страница может отрисоваться и при
      //    упавшем запросе — тогда пользователь видит пустой список вместо
      //    ошибки, и это худший из вариантов.
      expect(serverErrors, `${path}: серверные ошибки`).toEqual([]);

      // 5. Сырых ключей перевода на экране быть не должно.
      const text = (await main.innerText()).slice(0, 20_000);
      expect(text, `${path}: непереведённый ключ`).not.toMatch(
        /\bhr\.(pages|nav|fields)\.[a-zA-Z.]+/,
      );

      // 6. Ошибки консоли показываем в сообщении, но не валим тест: React в
      //    dev-режиме шумит предупреждениями, и падать на них — значит
      //    получить спеку, которую все игнорируют.
      if (consoleErrors.length) {
        console.log(`  [${path}] ошибки консоли:`, consoleErrors.slice(0, 3));
      }
    });
  }
});

test.describe("HR: карточка сотрудника", () => {
  test("список открывается и ведёт в карточку", async ({ page }) => {
    const { serverErrors } = watch(page);
    await login(page);
    await page.goto("/hr/employees");

    const main = page.locator("main").first();
    await expect(main).toBeVisible({ timeout: 20_000 });

    // Если сотрудники есть — первая строка обязана открывать карточку.
    const rows = page.locator("tbody tr");
    if ((await rows.count()) > 0) {
      await rows.first().click();
      await page.waitForTimeout(1500);
      // Либо перешли в карточку, либо открылась боковая панель — оба
      // варианта законны, недопустим только упавший рендер.
      await expect(page.locator("main").first()).toBeVisible();
    }

    expect(serverErrors).toEqual([]);
  });
});
