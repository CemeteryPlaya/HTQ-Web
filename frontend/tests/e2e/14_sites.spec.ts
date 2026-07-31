/**
 * Объекты (площадки) — сквозной проход по живому стеку.
 *
 * ВАЖНО: гонять только против ЛОКАЛЬНОЙ базы. Эти тесты создают и удаляют
 * данные, а корневой `.env` по умолчанию направляет backend на боевую БД
 * VPS. Стек для E2E поднимается так:
 *
 *   docker compose -f docker-compose.yml -f docker-compose.dev.yml \
 *                  -f docker-compose.localdb.yml -f docker-compose.test.yml up -d
 *
 * `docker-compose.localdb.yml` пинит `DB_HOST: db` на все backend-процессы;
 * проверить можно так: `docker compose ... exec backend-web printenv DB_HOST`.
 *
 * Тесты проверяют то, что модульные не видят: настоящую цепочку
 * nginx/vite → Django → Postgres и согласованность правил между слоями.
 */
import { test, expect } from "./fixtures";

const API = "/api/tasks/v1";
const stamp = () => Date.now() + Math.floor(Math.random() * 1000);

test.describe("Объекты", () => {
  test("объект создаётся, ищется и удаляется", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const name = `E2E объект ${stamp()}`;

    const created = await request.post(`${API}/sites/`, {
      headers: auth,
      data: { name, region: "Актюбинская область", code: `E2E${stamp()}` },
    });
    expect(created.status()).toBe(201);
    const site = await created.json();
    expect(site.status).toBe("active");
    expect(site.color).toBe("#0ea5e9");

    // Поиск по подстроке — тот же путь, которым ходит фильтр на странице.
    const found = await request.get(
      `${API}/sites/?search=${encodeURIComponent(name.slice(0, 12))}`,
      { headers: auth },
    );
    expect(found.ok()).toBeTruthy();
    expect((await found.json()).map((s: any) => s.id)).toContain(site.id);

    const removed = await request.delete(`${API}/sites/${site.id}/`, {
      headers: auth,
    });
    expect(removed.status()).toBe(204);
  });

  test("обычный пользователь читает справочник, но не правит его", async ({
    request,
    adminTokens,
  }) => {
    // Без токена — 401; это единственная проверка, которую можно сделать
    // не заводя второго пользователя.
    const anon = await request.get(`${API}/sites/`);
    expect(anon.status()).toBe(401);

    const withToken = await request.get(`${API}/sites/`, {
      headers: { Authorization: `Bearer ${adminTokens.access}` },
    });
    expect(withToken.status()).toBe(200);
  });

  test("объект с задачей не удаляется, а сообщает почему", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const site = await (
      await request.post(`${API}/sites/`, {
        headers: auth,
        data: { name: `E2E занятый ${stamp()}` },
      })
    ).json();

    const task = await (
      await request.post(`${API}/tasks/`, {
        headers: auth,
        data: { summary: `E2E задача ${stamp()}`, site_id: site.id },
      })
    ).json();
    expect(task.site_id).toBe(site.id);
    expect(task.site_name).toBe(site.name);

    const blocked = await request.delete(`${API}/sites/${site.id}/`, {
      headers: auth,
    });
    expect(blocked.status()).toBe(409);
    // Текст называет счётчики — на странице он показывается как есть.
    expect((await blocked.json()).detail).toContain("задач");

    await request.delete(`${API}/tasks/${task.id}/`, { headers: auth });
    // Задача удалена мягко (is_deleted), поэтому объект всё ещё занят —
    // это ожидаемое поведение, а не недочёт очистки.
    await request.patch(`${API}/sites/${site.id}/`, {
      headers: auth,
      data: { status: "closed" },
    });
  });

  test("объект задачи обязан входить в объекты её проекта", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const alga = await (
      await request.post(`${API}/sites/`, {
        headers: auth,
        data: { name: `E2E Алга ${stamp()}` },
      })
    ).json();
    const stranger = await (
      await request.post(`${API}/sites/`, {
        headers: auth,
        data: { name: `E2E Сазаган ${stamp()}` },
      })
    ).json();
    const project = await (
      await request.post(`${API}/projects/`, {
        headers: auth,
        data: { name: `E2E проект ${stamp()}` },
      })
    ).json();

    await request.put(`${API}/projects/${project.id}/sites/`, {
      headers: auth,
      data: { site_ids: [alga.id] },
    });

    // Чужой объект — 400 с человеческим текстом, а не 500.
    const rejected = await request.post(`${API}/tasks/`, {
      headers: auth,
      data: {
        summary: `E2E чужой объект ${stamp()}`,
        project_id: project.id,
        site_id: stranger.id,
      },
    });
    expect(rejected.status()).toBe(400);
    expect((await rejected.json()).detail).toContain("проект");

    // Единственный объект проекта наследуется, когда его не прислали.
    const inherited = await request.post(`${API}/tasks/`, {
      headers: auth,
      data: { summary: `E2E наследник ${stamp()}`, project_id: project.id },
    });
    expect(inherited.status()).toBe(201);
    expect((await inherited.json()).site_id).toBe(alga.id);

    // Объекты видны в карточке проекта — это то, что рисует чипы в роадмапе.
    const withSites = await (
      await request.get(`${API}/projects/${project.id}/`, { headers: auth })
    ).json();
    expect(withSites.site_ids).toEqual([alga.id]);
    expect(withSites.sites[0].name).toBe(alga.name);
  });

  test("фильтры по объекту и по его отсутствию дополняют друг друга", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const site = await (
      await request.post(`${API}/sites/`, {
        headers: auth,
        data: { name: `E2E фильтр ${stamp()}` },
      })
    ).json();
    await request.post(`${API}/tasks/`, {
      headers: auth,
      data: { summary: `E2E на объекте ${stamp()}`, site_id: site.id },
    });

    const onSite = await (
      await request.get(`${API}/tasks/?site_id=${site.id}&limit=200`, {
        headers: auth,
      })
    ).json();
    expect(onSite.length).toBeGreaterThan(0);
    expect(onSite.every((t: any) => t.site_id === site.id)).toBeTruthy();

    const withoutSite = await (
      await request.get(`${API}/tasks/?no_site=true&limit=200`, {
        headers: auth,
      })
    ).json();
    expect(withoutSite.every((t: any) => t.site_id === null)).toBeTruthy();
  });

  test("отчёты дают разрезы по объектам и проектам", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const stats = await (
      await request.get(`${API}/tasks/stats/`, { headers: auth })
    ).json();

    expect(Array.isArray(stats.by_site)).toBeTruthy();
    expect(Array.isArray(stats.by_project)).toBeTruthy();

    // Сумма разреза сходится с total — иначе отчёт врёт. Это тот самый
    // класс ошибки, из-за которого тайлы «В работе»/«Завершено» годами
    // не сходились с «Всего».
    const bySite = stats.by_site.reduce(
      (sum: number, row: any) => sum + row.count,
      0,
    );
    const byProject = stats.by_project.reduce(
      (sum: number, row: any) => sum + row.count,
      0,
    );
    expect(bySite).toBe(stats.total);
    expect(byProject).toBe(stats.total);
  });

  test("тайлы отчёта сходятся с суммой по статусам", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const stats = await (
      await request.get(`${API}/tasks/stats/`, { headers: auth })
    ).json();

    const OPEN = ["backlog", "todo"];
    const ACTIVE = ["in_progress", "in_review", "blocked"];
    const TERMINAL = ["done", "cancelled"];
    const sum = (keys: string[]) =>
      keys.reduce((acc, k) => acc + (stats.by_status[k] ?? 0), 0);

    // Именно эта арифметика была сломана: старая версия складывала
    // open + in_progress + in_review, а `open` в этом бэкенде не бывает.
    expect(sum(OPEN) + sum(ACTIVE) + sum(TERMINAL)).toBe(stats.total);
    // И ни одного статуса вне известной семёрки.
    for (const key of Object.keys(stats.by_status)) {
      expect([...OPEN, ...ACTIVE, ...TERMINAL]).toContain(key);
    }
  });
});
