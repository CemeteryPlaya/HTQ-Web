/**
 * Проекты — управление в браузере и связка проект → объект → задача.
 *
 * Гонять против dev-сервера Vite и ЛОКАЛЬНОЙ базы.
 *
 * Ради чего спека: до появления страницы `/manage/projects` назначить
 * проекту объект было неоткуда — `setProjectSites` не вызывал ни один
 * компонент. Из-за этого форма задачи ВСЕГДА показывала «У проекта нет
 * объектов» и предлагала весь справочник. Главный тест здесь — четвёртый:
 * он проверяет не форму, а саму связку, ради которой всё делалось.
 *
 * Спека убирает за собой всё созданное (у проектов и объектов есть DELETE),
 * поэтому в справочниках после прогона не остаётся мусора.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE } from "./fixtures";
import type { APIRequestContext, Page } from "@playwright/test";

const API = `${API_BASE}/api/tasks/v1`;
const stamp = () => Date.now() + Math.floor(Math.random() * 10000);

async function login(page: Page) {
  // Язык прибиваем явно: LanguageDetector иначе берёт локаль машины.
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

const auth = (token: string) => ({
  headers: { Authorization: `Bearer ${token}` },
});

/** Пара объектов под тест — с узнаваемыми именами и своим DELETE. */
async function makeSites(request: APIRequestContext, token: string) {
  const mk = async (label: string) => {
    const resp = await request.post(`${API}/sites/`, {
      ...auth(token),
      data: { name: `UI ${label} ${stamp()}`, color: "#0ea5e9" },
    });
    expect(resp.status(), await resp.text()).toBe(201);
    return resp.json();
  };
  return { alga: await mk("Алга"), sazagan: await mk("Сазаган") };
}

test.describe("Проекты: управление", () => {
  test("проект создаётся из формы и помечается как «без объектов»", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    await page.goto("/manage/projects");

    await expect(
      page.getByRole("heading", { name: /^Проекты$/ }).first(),
    ).toBeVisible({ timeout: 20_000 });

    const name = `UI проект ${stamp()}`;
    try {
      await page.getByRole("button", { name: "Новый проект" }).click();

      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Название").fill(name);
      await dialog.getByLabel("Описание").fill("Создан браузерным тестом");
      await dialog.getByRole("button", { name: "Сохранить" }).click();

      await expect(dialog).not.toBeVisible({ timeout: 15_000 });

      // Карточка появилась — значит список перезапросился, а не дорисовался.
      const card = page.getByRole("button").filter({ hasText: name });
      await expect(card).toBeVisible({ timeout: 15_000 });

      // И сразу видно главное: объектов у проекта нет.
      await expect(card.getByText("Объекты не заданы")).toBeVisible();
    } finally {
      // Именно finally: проект заводится формой, поэтому его id заранее
      // неизвестен, а падение проверки не должно оставлять запись в
      // справочнике — так в базе и накопились прошлые «UI …».
      const list = await (
        await page.request.get(`${API}/projects/`, auth(token))
      ).json();
      const created = (Array.isArray(list) ? list : list.items).find(
        (p: { name: string }) => p.name === name,
      );
      if (created) {
        await page.request.delete(`${API}/projects/${created.id}`, auth(token));
      }
    }
  });

  test("объекты назначаются, основной помечается звёздочкой", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    const { alga, sazagan } = await makeSites(page.request, token);
    const project = await (
      await page.request.post(`${API}/projects/`, {
        ...auth(token),
        data: { name: `UI объекты ${stamp()}` },
      })
    ).json();

    try {
      await page.goto("/manage/projects");
      await page.getByRole("button").filter({ hasText: project.name }).click();

      await page.getByRole("tab", { name: /^Объекты/ }).click();

      // Отмечаем оба объекта и делаем «Алгу» основным.
      await page.getByRole("checkbox").and(page.locator(`#site-${alga.id}`)).click();
      await page.getByRole("checkbox").and(page.locator(`#site-${sazagan.id}`)).click();
      const algaRow = page.locator("div").filter({ hasText: alga.name }).last();
      await algaRow.getByRole("button", { name: "Основной объект" }).click();

      await page.getByRole("button", { name: "Сохранить объекты" }).click();

      // Предупреждение ушло, чипы появились, основной со звездой.
      await expect(page.getByText("Объекты не заданы")).toHaveCount(0, {
        timeout: 15_000,
      });
      await expect(page.getByRole("tab", { name: "Объекты (2)" })).toBeVisible();
      await expect(page.getByText(`★ ${alga.name}`)).toBeVisible();

      // Сервер действительно сохранил, а не только экран перерисовался.
      const saved = await (
        await page.request.get(`${API}/projects/${project.id}/sites/`, auth(token))
      ).json();
      expect(saved.map((s: { id: number }) => s.id).sort())
        .toEqual([alga.id, sazagan.id].sort());
      expect(saved.find((s: { is_primary: boolean }) => s.is_primary).id).toBe(alga.id);
    } finally {
      await page.request.delete(`${API}/projects/${project.id}`, auth(token));
      for (const site of [alga, sazagan]) {
        await page.request.delete(`${API}/sites/${site.id}`, auth(token));
      }
    }
  });

  test("СВЯЗКА: форма задачи предлагает только объекты своего проекта", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    const { alga, sazagan } = await makeSites(page.request, token);
    // Третий объект — контрольный: он НЕ должен попасть в список формы.
    const foreign = await (
      await page.request.post(`${API}/sites/`, {
        ...auth(token),
        data: { name: `UI Посторонний ${stamp()}`, color: "#f59e0b" },
      })
    ).json();

    const project = await (
      await page.request.post(`${API}/projects/`, {
        ...auth(token),
        data: { name: `UI связка ${stamp()}` },
      })
    ).json();
    await page.request.put(`${API}/projects/${project.id}/sites/`, {
      ...auth(token),
      data: { site_ids: [alga.id, sazagan.id], primary_site_id: alga.id },
    });

    try {
      await page.goto("/tasks");
      await page.getByRole("button", { name: /Создать/i }).first().click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 15_000 });

      // Селект проекта скрыт, пока задача «отдельная» — сначала радио.
      await dialog.getByLabel("Привязать к проекту").click();

      await dialog.getByRole("combobox").filter({ hasText: "Выбрать проект" }).click();
      await page.getByRole("option", { name: project.name }).click();

      await dialog.getByRole("combobox").filter({ hasText: "Выбрать объект" }).click();

      // Оба объекта проекта предлагаются…
      await expect(page.getByRole("option", { name: alga.name })).toBeVisible();
      await expect(page.getByRole("option", { name: sazagan.name })).toBeVisible();
      // …а посторонний — нет. Это и есть та связка, ради которой
      // существует вкладка «Объекты» на странице проектов.
      await expect(
        page.getByRole("option", { name: foreign.name }),
        "объект вне проекта не должен предлагаться",
      ).toHaveCount(0);
    } finally {
      await page.request.delete(`${API}/projects/${project.id}`, auth(token));
      for (const site of [alga, sazagan, foreign]) {
        await page.request.delete(`${API}/sites/${site.id}`, auth(token));
      }
    }
  });

  test("правка проекта меняет статус, карточка перерисовывается", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    const project = await (
      await page.request.post(`${API}/projects/`, {
        ...auth(token),
        data: { name: `UI правка ${stamp()}`, status: "active" },
      })
    ).json();

    try {
      await page.goto("/manage/projects");
      await page.getByRole("button").filter({ hasText: project.name }).click();
      await page.getByRole("button", { name: "Изменить" }).click();

      const dialog = page.getByRole("dialog");
      await dialog.getByRole("combobox").first().click();
      await page.getByRole("option", { name: "Завершён" }).click();
      await dialog.getByRole("button", { name: "Сохранить" }).click();

      await expect(dialog).not.toBeVisible({ timeout: 15_000 });
      const card = page.getByRole("button").filter({ hasText: project.name });
      await expect(card.getByText("Завершён")).toBeVisible({ timeout: 15_000 });
    } finally {
      await page.request.delete(`${API}/projects/${project.id}`, auth(token));
    }
  });

  test("удаление называет число задач и не удаляет их самих", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    const project = await (
      await page.request.post(`${API}/projects/`, {
        ...auth(token),
        data: { name: `UI удаление ${stamp()}` },
      })
    ).json();
    const task = await (
      await page.request.post(`${API}/tasks/`, {
        ...auth(token),
        data: { summary: `UI задача ${stamp()}`, project_id: project.id },
      })
    ).json();

    try {
      await page.goto("/manage/projects");
      await page.getByRole("button").filter({ hasText: project.name }).click();
      await page.getByRole("button", { name: "Удалить" }).first().click();

      const dialog = page.getByRole("dialog");
      // Задача — SET_NULL: она переживёт удаление, и пользователю это
      // говорят числом, а не общей формулировкой.
      await expect(dialog.getByText(/Задач в проекте: 1/)).toBeVisible();
      await dialog.getByRole("button", { name: "Удалить" }).click();

      await expect(
        page.getByRole("button").filter({ hasText: project.name }),
      ).toHaveCount(0, { timeout: 15_000 });

      // Задача осталась, но связи с проектом больше нет. Читаем сырой
      // ответ API, поэтому поле называется project_id (клиентский
      // normalizeTask переименовывает его в project, но здесь его нет).
      const after = await (
        await page.request.get(`${API}/tasks/${task.id}/`, auth(token))
      ).json();
      expect(after.id).toBe(task.id);
      expect(after.project_id).toBeNull();
    } finally {
      await page.request.delete(`${API}/tasks/${task.id}/`, auth(token));
      await page.request.delete(`${API}/projects/${project.id}`, auth(token));
    }
  });

  test("вкладка «Задачи» показывает задачи проекта", async ({
    page,
    adminTokens,
  }) => {
    const token = adminTokens.access;
    await login(page);
    const project = await (
      await page.request.post(`${API}/projects/`, {
        ...auth(token),
        data: { name: `UI задачи ${stamp()}` },
      })
    ).json();
    const summary = `UI подзадача ${stamp()}`;
    const task = await (
      await page.request.post(`${API}/tasks/`, {
        ...auth(token),
        data: { summary, project_id: project.id },
      })
    ).json();

    try {
      await page.goto("/manage/projects");
      await page.getByRole("button").filter({ hasText: project.name }).click();
      await page.getByRole("tab", { name: /^Задачи/ }).click();
      await expect(page.getByText(summary)).toBeVisible({ timeout: 15_000 });
    } finally {
      await page.request.delete(`${API}/tasks/${task.id}/`, auth(token));
      await page.request.delete(`${API}/projects/${project.id}`, auth(token));
    }
  });
});
