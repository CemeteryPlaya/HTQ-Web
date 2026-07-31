/**
 * HR — функциональный проход по девяти разделам бокового меню:
 * PMO, публичные ссылки, учёт времени, рекрутинг, архив, документы,
 * кадровая история, производственный календарь, штатное расписание.
 *
 * Гонять только против ЛОКАЛЬНОЙ базы (см. шапку 14_sites.spec.ts): тесты
 * создают отделы, должности, сотрудников, ОУП, ссылки, документы и строки
 * штатного расписания.
 *
 * Чем это отличается от 17_hr_api.spec.ts: тот проходит по справочникам
 * (отделы/должности/сотрудники) и проверяет, что маршруты живы. Здесь —
 * ПРАВИЛА внутри каждого раздела: что суммарная нагрузка считается по
 * активным членствам, что одноразовая ссылка не открывается дважды и её
 * отказ попадает в журнал, что перерыв вычитается из дневной нормы, что
 * праздник уменьшает число рабочих дней, что ФОТ = ставки × оклад.
 * Юнит-тесты в apps/hr/tests проверяют это на подготовленных объектах;
 * здесь та же логика проходит через маршрут, авторизацию, сериализацию и
 * настоящий Postgres.
 */
import { test, expect } from "./fixtures";

const API = "/api/hr/v1";
const stamp = () => Date.now() + Math.floor(Math.random() * 10000);
const today = () => new Date().toISOString().slice(0, 10);

/** Дата строкой без часовых поясов.
 *
 *  `new Date(y, m, d).toISOString()` считает от локальной полуночи и в
 *  UTC+N съезжает на день назад — на этом тест сменного графика уже
 *  ошибался на сутки. Собираем строку арифметикой, а не через Date. */
const ymd = (year: number, month: number, day: number) =>
  `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

/** Почта кандидата валидируется как EmailStr, а он отвергает
 *  зарезервированный TLD `.test` — для откликов нужен настоящий домен
 *  (у сотрудников поле обычное строковое, там `@htq.test` проходит). */
const candidateEmail = () => `cand${stamp()}@example.com`;

type Ctx = { headers: Record<string, string> };

async function ok(request: any, url: string, ctx: Ctx) {
  const resp = await request.get(url, ctx);
  expect(resp.status(), `GET ${url}`).toBe(200);
  return resp.json();
}

async function created(request: any, url: string, ctx: Ctx, data: any) {
  const resp = await request.post(url, { ...ctx, data });
  expect(resp.status(), `POST ${url} -> ${await resp.text()}`).toBe(201);
  return resp.json();
}

/** Отдел + должность + сотрудник — минимальная связка: у Employee оба FK
 *  PROTECT NOT NULL, а половина разделов ниже без сотрудника не работает. */
async function makePerson(request: any, ctx: Ctx) {
  const dept = await (
    await request.post(`${API}/departments/`, {
      ...ctx,
      data: { name: `E2E отдел ${stamp()}` },
    })
  ).json();
  // weight глобально уникален (position_service.WeightTaken) при дефолте
  // 100 — берём из большого диапазона, чтобы не столкнуться с сидом.
  const position = await created(request, `${API}/positions/`, ctx, {
    title: `E2E должность ${stamp()}`,
    department_id: dept.id,
    weight: 10_000 + Math.floor(Math.random() * 5_000_000),
  });
  const employee = await created(request, `${API}/employees/`, ctx, {
    first_name: "Тест",
    last_name: `Модулев${stamp()}`,
    email: `mod${stamp()}@htq.test`,
    hire_date: today(),
    department_id: dept.id,
    position_id: position.id,
  });
  return { dept, position, employee };
}

// ─────────────────────────────── 1. PMO ────────────────────────────────

test.describe("HR: PMO (проектные офисы)", () => {
  test("ОУП заводится, набирает участников и попадает в граф", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    const pmo = await created(request, `${API}/pmo/`, ctx, {
      name: `E2E ОУП ${stamp()}`,
      code: `E2E-${stamp()}`,
      description: "Проверка раздела PMO",
    });
    expect(pmo.status).toBe("active");

    const member = await request.post(`${API}/pmo/${pmo.id}/members`, {
      ...ctx,
      data: {
        employee_id: employee.id,
        membership_type: "permanent",
        position_in_pmo: "Инженер проекта",
        allocation_percent: 60,
        is_primary: true,
      },
    });
    expect(member.status(), await member.text()).toBe(201);

    // Список отдаёт РАЗВЁРНУТОГО участника: имя и первичную должность
    // резолвит сервер, чтобы клиент не джойнил сам.
    const members = await ok(request, `${API}/pmo/${pmo.id}/members`, ctx);
    expect(members.length).toBe(1);
    expect(members[0].employee_name).toContain("Модулев");
    expect(members[0].position_in_pmo).toBe("Инженер проекта");
    expect(members[0].is_primary).toBe(true);

    // Граф: узел ОУП + узел сотрудника, ребро между ними.
    const chart = await ok(request, `${API}/pmo/${pmo.id}/org-chart`, ctx);
    expect(chart.nodes.some((n: any) => n.id === `pmo_${pmo.id}`)).toBeTruthy();
    expect(
      chart.nodes.some((n: any) => n.id === `emp_${employee.id}`),
    ).toBeTruthy();
    expect(chart.edges).toContainEqual({
      source: `pmo_${pmo.id}`,
      target: `emp_${employee.id}`,
      relation_type: "permanent",
    });

    // Обратная сторона связи — карточка сотрудника знает про свой ОУП.
    const mine = await ok(request, `${API}/employees/${employee.id}/pmos`, ctx);
    expect(mine.map((p: any) => p.pmo_id)).toContain(pmo.id);
    expect(mine[0].allocation_percent).toBe(60);
  });

  test("повторное активное членство и второй лид отбиваются 409", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const second = await makePerson(request, ctx);

    const pmo = await created(request, `${API}/pmo/`, ctx, {
      name: `E2E ОУП ${stamp()}`,
      code: `E2E-${stamp()}`,
    });
    const add = (data: any) =>
      request.post(`${API}/pmo/${pmo.id}/members`, { ...ctx, data });

    expect((await add({ employee_id: employee.id, is_primary: true })).status())
      .toBe(201);

    // Тот же человек второй раз, пока первое членство активно.
    const dup = await add({ employee_id: employee.id });
    expect(dup.status()).toBe(409);
    expect((await dup.json()).detail).toContain("already an active member");

    // Второй лид на том же ОУП.
    const primary = await add({
      employee_id: second.employee.id,
      is_primary: true,
    });
    expect(primary.status()).toBe(409);
    expect((await primary.json()).detail).toContain("already has a primary");

    // А обычным участником тот же человек проходит.
    expect((await add({ employee_id: second.employee.id })).status()).toBe(201);
  });

  test("уникальный код ОУП и 409 на дубль", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const code = `E2E-DUP-${stamp()}`;
    await created(request, `${API}/pmo/`, ctx, { name: "Первый", code });
    const again = await request.post(`${API}/pmo/`, {
      ...ctx,
      data: { name: "Второй", code },
    });
    expect(again.status()).toBe(409);
  });

  test("закрытие ОУП закрывает активные членства и запрещает новые", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const extra = await makePerson(request, ctx);

    const pmo = await created(request, `${API}/pmo/`, ctx, {
      name: `E2E ОУП ${stamp()}`,
      code: `E2E-${stamp()}`,
    });
    await request.post(`${API}/pmo/${pmo.id}/members`, {
      ...ctx,
      data: { employee_id: employee.id },
    });

    // DELETE — это мягкое закрытие, а не удаление: ОУП остаётся читаемым.
    const closed = await request.delete(`${API}/pmo/${pmo.id}`, ctx);
    expect(closed.status()).toBeLessThan(300);

    const after = await ok(request, `${API}/pmo/${pmo.id}`, ctx);
    expect(after.status).toBe("closed");

    // Членство не исчезло, а получило дату окончания сегодняшним днём.
    const members = await ok(request, `${API}/pmo/${pmo.id}/members`, ctx);
    expect(members[0].to_date).toBe(today());

    // И в активную нагрузку сотрудника закрытый ОУП больше не входит.
    const mine = await ok(request, `${API}/employees/${employee.id}/pmos`, ctx);
    expect(mine.map((p: any) => p.pmo_id)).not.toContain(pmo.id);

    // Добирать людей в закрытый ОУП нельзя.
    const late = await request.post(`${API}/pmo/${pmo.id}/members`, {
      ...ctx,
      data: { employee_id: extra.employee.id },
    });
    expect(late.status()).toBe(409);
  });

  test("несуществующий ОУП и несуществующий сотрудник дают 404", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    expect((await request.get(`${API}/pmo/999999`, ctx)).status()).toBe(404);
    expect(
      (await request.get(`${API}/pmo/999999/members`, ctx)).status(),
    ).toBe(404);

    const pmo = await created(request, `${API}/pmo/`, ctx, {
      name: `E2E ОУП ${stamp()}`,
      code: `E2E-${stamp()}`,
    });
    const ghost = await request.post(`${API}/pmo/${pmo.id}/members`, {
      ...ctx,
      data: { employee_id: 999999 },
    });
    expect(ghost.status()).toBe(404);
  });
});

// ────────────────────── 2. Публичные ссылки ───────────────────────────

test.describe("HR: публичные ссылки", () => {
  test("токен показывается один раз и открывает оргструктуру", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };

    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E ссылка ${stamp()}`,
      viewer_label: "ТОО Проверка",
      max_level: 5,
      link_type: "one_time",
    });
    expect(link.token, "raw token отдаётся ровно при создании").toBeTruthy();

    // В списке и в detail токена быть не должно НИКОГДА — в базе лежит
    // только SHA-256, показать его повторно попросту нечем.
    const list = await ok(request, `${API}/share-links/`, ctx);
    const mine = list.find((l: any) => l.id === link.id);
    expect(mine).toBeTruthy();
    expect(mine.token).toBeUndefined();
    expect(JSON.stringify(list)).not.toContain(link.token);

    // Публичное открытие — без авторизации.
    const pub = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(pub.status(), await pub.text()).toBe(200);
    const payload = await pub.json();
    expect(payload.tree.nodes.length).toBeGreaterThan(0);
    expect(payload.watermark.viewer_label).toBe("ТОО Проверка");

    // Ограничение по уровню соблюдается в САМОМ JSON, а не только в UI.
    for (const node of payload.tree.nodes) {
      if (node.level != null) expect(node.level).toBeLessThanOrEqual(5);
    }
    // Рёбра не должны ссылаться на срезанные узлы.
    const ids = new Set(payload.tree.nodes.map((n: any) => n.id));
    for (const edge of payload.tree.edges) {
      expect(ids.has(edge.source)).toBeTruthy();
      expect(ids.has(edge.target)).toBeTruthy();
    }
  });

  test("одноразовая ссылка не открывается дважды, отказ попадает в журнал", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E одноразовая ${stamp()}`,
      link_type: "one_time",
    });

    const first = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(first.status()).toBe(200);

    const second = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(second.status(), "второе открытие одноразовой ссылки").toBe(410);

    // Журнал — то, ради чего раздел существует: видно и создание, и
    // успешное открытие, и отказ.
    const audit = await ok(request, `${API}/share-links/${link.id}/audit`, ctx);
    const actions = audit.map((a: any) => a.action);
    expect(actions).toContain("created");
    expect(actions).toContain("open");
    expect(actions).toContain("denied_used");
  });

  test("отозванная ссылка отдаёт 410 и пишет отказ", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E отзыв ${stamp()}`,
      link_type: "permanent_with_expiry",
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    });

    const revoke = await request.delete(`${API}/share-links/${link.id}`, ctx);
    expect(revoke.status()).toBeLessThan(300);

    const denied = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(denied.status()).toBe(410);

    const audit = await ok(request, `${API}/share-links/${link.id}/audit`, ctx);
    expect(audit.map((a: any) => a.action)).toContain("denied_revoked");

    // Отзыв идемпотентен — второй раз не должен падать.
    expect(
      (await request.delete(`${API}/share-links/${link.id}`, ctx)).status(),
    ).toBeLessThan(300);
  });

  test("истёкшая ссылка отдаёт 410", async ({ request, adminTokens }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E истёкшая ${stamp()}`,
      link_type: "time_limited",
      expires_at: new Date(Date.now() - 60_000).toISOString(),
    });
    const resp = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(resp.status()).toBe(410);
  });

  test("ссылка на карточку не открывается как оргструктура", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E карточка ${stamp()}`,
      link_type: "permanent_with_expiry",
      target_type: "employee",
      target_employee_id: employee.id,
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    });

    // Подмена маршрута раскрыла бы всю компанию вместо одной карточки.
    // Ответ намеренно 404, а не 403: по разнице кодов нельзя перебором
    // определить тип цели чужого токена.
    const wrong = await request.get(`${API}/public/org/${link.token}`, {
      headers: {},
    });
    expect(wrong.status()).toBe(404);

    // По своему маршруту та же ссылка работает.
    const right = await request.get(`${API}/public/employee/${link.token}`, {
      headers: {},
    });
    expect(right.status(), await right.text()).toBe(200);
    expect((await right.json()).card).toBeTruthy();
  });

  test("мусорный токен — 404, чужая ссылка не видна", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const bogus = await request.get(`${API}/public/org/definitely-not-a-token`, {
      headers: {},
    });
    expect(bogus.status()).toBe(404);

    // Журнал чужой (несуществующей) ссылки — 404, а не пустой список.
    const audit = await request.get(
      `${API}/share-links/00000000-0000-0000-0000-000000000000/audit`,
      ctx,
    );
    expect(audit.status()).toBe(404);
  });

  test("публичная выдача не содержит контактов и зарплат", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    await makePerson(request, ctx);
    const link = await created(request, `${API}/share-links/`, ctx, {
      label: `E2E PII ${stamp()}`,
      max_level: 10,
      link_type: "one_time",
    });
    const payload = await (
      await request.get(`${API}/public/org/${link.token}`, { headers: {} })
    ).json();

    // Проверяем не «нет строки в JSON», а отсутствие именно этих ключей в
    // meta: имя сотрудника в выдаче быть должно, его телефон — нет.
    for (const node of payload.tree.nodes) {
      const meta = node.meta ?? {};
      for (const field of ["email", "phone", "salary", "iin", "birthday", "home_address"]) {
        expect(meta[field], `${field} в публичной выдаче`).toBeUndefined();
      }
    }
  });
});

// ──────────────────────── 3. Учёт времени ─────────────────────────────

test.describe("HR: учёт времени", () => {
  test("запись создаётся, перерыв вычитается из дневной нормы", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const day = today();

    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: employee.id,
      date: day,
      start_time: "09:00:00",
      end_time: "18:00:00",
      break_minutes: 60,
      description: "E2E рабочий день",
      project: "E2E проект",
    });
    expect(entry.break_minutes).toBe(60);

    // 9 часов минус час перерыва = 480 минут. Это и есть весь смысл
    // раздела: считать не «с и до», а фактически отработанное.
    const daily = await ok(
      request,
      `${API}/time-tracking/reports/daily?employee_id=${employee.id}&date=${day}`,
      ctx,
    );
    expect(daily.total_minutes).toBe(480);
    expect(daily.entries.length).toBe(1);

    await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx);
  });

  test("недельный отчёт всегда даёт 7 дней, включая пустые", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    // Понедельник текущей недели.
    const now = new Date();
    const monday = new Date(now);
    monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    const weekStart = monday.toISOString().slice(0, 10);

    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: employee.id,
      date: weekStart,
      start_time: "10:00:00",
      end_time: "14:00:00",
      break_minutes: 0,
    });

    const weekly = await ok(
      request,
      `${API}/time-tracking/reports/weekly?employee_id=${employee.id}&week_start=${weekStart}`,
      ctx,
    );
    expect(weekly.daily.length, "неделя — всегда 7 ячеек").toBe(7);
    expect(weekly.total_minutes).toBe(240);
    expect(weekly.daily[0].total_minutes).toBe(240);
    // Сумма по дням обязана сходиться с итогом — иначе таблица врёт.
    const sum = weekly.daily.reduce(
      (acc: number, d: any) => acc + d.total_minutes,
      0,
    );
    expect(sum).toBe(weekly.total_minutes);

    await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx);
  });

  test("месячный отчёт группирует записи по неделям", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const mk = (d: number) =>
      `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

    // Два дня, заведомо в разных неделях месяца.
    const a = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: employee.id,
      date: mk(2),
      start_time: "09:00:00",
      end_time: "13:00:00",
    });
    const b = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: employee.id,
      date: mk(20),
      start_time: "09:00:00",
      end_time: "12:00:00",
    });

    const monthly = await ok(
      request,
      `${API}/time-tracking/reports/monthly?employee_id=${employee.id}&year=${year}&month=${month}`,
      ctx,
    );
    expect(monthly.total_minutes).toBe(420);
    expect(monthly.weekly.length).toBeGreaterThanOrEqual(2);

    for (const id of [a.id, b.id]) {
      await request.delete(`${API}/time-tracking/entries/${id}`, ctx);
    }
  });

  test("конец раньше начала не сохраняется (422)", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const bad = await request.post(`${API}/time-tracking/entries/`, {
      ...ctx,
      data: {
        employee_id: employee.id,
        date: today(),
        start_time: "18:00:00",
        end_time: "09:00:00",
      },
    });
    expect(bad.status()).toBe(422);
  });

  test("правка записи пересчитывает отчёт", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const day = today();
    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: employee.id,
      date: day,
      start_time: "09:00:00",
      end_time: "17:00:00",
    });

    const patched = await request.patch(
      `${API}/time-tracking/entries/${entry.id}`,
      { ...ctx, data: { break_minutes: 30 } },
    );
    expect(patched.status(), await patched.text()).toBe(200);

    const daily = await ok(
      request,
      `${API}/time-tracking/reports/daily?employee_id=${employee.id}&date=${day}`,
      ctx,
    );
    expect(daily.total_minutes).toBe(8 * 60 - 30);

    expect(
      (await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx)).status(),
    ).toBeLessThan(300);
    // Одиночного GET у записи нет (только PUT/PATCH/DELETE), поэтому
    // отсутствие проверяем повторным удалением.
    expect(
      (await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx)).status(),
    ).toBe(404);
  });

  test("КОНТРАКТ: корень раздела отдаёт конверт с items", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const root = await ok(request, `${API}/time-tracking/`, ctx);

    // Фиксируем фактическую форму ответа. Страница HRTimeTracking.tsx
    // типизирует этот ответ как TimeRecord[] и делает records.map(...) —
    // на объекте это TypeError. Тест закрепляет сторону БЭКЕНДА (она же
    // соответствует /entries/), чтобы починка фронта не разъехалась ещё
    // раз; браузерная половина расхождения — в 20_hr_modules_ui.spec.ts.
    expect(Array.isArray(root), "корень отдаёт объект, а не массив").toBe(false);
    expect(root).toHaveProperty("items");
    expect(Array.isArray(root.items)).toBe(true);
    expect(root).toHaveProperty("total");
    expect(root).toHaveProperty("page");
  });
});

// ────────────────────────── 4. Рекрутинг ──────────────────────────────

test.describe("HR: рекрутинг", () => {
  test("вакансия → отклик → найм, вся цепочка", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);

    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `E2E вакансия ${stamp()}`,
      department_id: dept.id,
      position_id: position.id,
      description: "Проверка раздела рекрутинга",
      requirements: "Опыт от года",
    });
    expect(vacancy.status).toBe("open");

    const application = await created(request, `${API}/applications/`, ctx, {
      vacancy_id: vacancy.id,
      candidate_name: `E2E Кандидат ${stamp()}`,
      candidate_email: candidateEmail(),
      candidate_phone: "+7 (700) 483-55-81",
    });
    expect(application.status).toBe("new");

    // Отклик виден в списке своей вакансии.
    const byVacancy = await ok(
      request,
      `${API}/vacancies/${vacancy.id}/applications`,
      ctx,
    );
    expect(byVacancy.map((a: any) => a.id)).toContain(application.id);

    // Прогон по воронке статусов — то, чем раздел живёт каждый день.
    for (const status of ["reviewed", "interview", "offer", "hired"]) {
      const moved = await request.post(
        `${API}/applications/${application.id}/status`,
        { ...ctx, data: { status, notes: `перевод в ${status}` } },
      );
      expect(moved.status(), `перевод в ${status}`).toBe(200);
      expect((await moved.json()).status).toBe(status);
    }

    // Закрытие вакансии проставляет дату.
    const closed = await request.delete(`${API}/vacancies/${vacancy.id}`, ctx);
    expect(closed.status()).toBeLessThan(300);
    const after = await ok(request, `${API}/vacancies/${vacancy.id}`, ctx);
    expect(after.status).toBe("closed");
    expect(after.closed_at).toBe(today());
  });

  test("пустой notes не затирает уже записанный комментарий", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `E2E вакансия ${stamp()}`,
      department_id: dept.id,
      position_id: position.id,
    });
    const application = await created(request, `${API}/applications/`, ctx, {
      vacancy_id: vacancy.id,
      candidate_name: `E2E Кандидат ${stamp()}`,
      candidate_email: candidateEmail(),
    });

    await request.post(`${API}/applications/${application.id}/status`, {
      ...ctx,
      data: { status: "reviewed", notes: "первый скрининг пройден" },
    });
    const blanked = await request.post(
      `${API}/applications/${application.id}/status`,
      { ...ctx, data: { status: "interview", notes: "" } },
    );
    expect(blanked.status()).toBe(200);
    expect((await blanked.json()).notes).toBe("первый скрининг пройден");
  });

  test("отклик на несуществующую вакансию — 404, не 422", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const resp = await request.post(`${API}/applications/`, {
      ...ctx,
      data: {
        vacancy_id: 999999,
        candidate_name: "Призрак",
        candidate_email: candidateEmail(),
      },
    });
    expect(resp.status()).toBe(404);
  });

  test("некорректная почта кандидата не сохраняется", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `E2E вакансия ${stamp()}`,
      department_id: dept.id,
      position_id: position.id,
    });
    const resp = await request.post(`${API}/applications/`, {
      ...ctx,
      data: {
        vacancy_id: vacancy.id,
        candidate_name: "Кривая почта",
        candidate_email: "не-почта",
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("фильтр вакансий по статусу и отделу", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `E2E фильтр ${stamp()}`,
      department_id: dept.id,
      position_id: position.id,
    });

    const byDept = await ok(
      request,
      `${API}/vacancies/?department_id=${dept.id}`,
      ctx,
    );
    expect(byDept.items.map((v: any) => v.id)).toEqual([vacancy.id]);

    const byStatus = await ok(request, `${API}/vacancies/?status=closed`, ctx);
    expect(byStatus.items.map((v: any) => v.id)).not.toContain(vacancy.id);
  });
});

// ─────────────────────────── 5. Архив ─────────────────────────────────

test.describe("HR: архив", () => {
  test("в архив попадают только завершённые отклики", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `E2E архив ${stamp()}`,
      department_id: dept.id,
      position_id: position.id,
    });

    const mkApp = async (name: string) =>
      created(request, `${API}/applications/`, ctx, {
        vacancy_id: vacancy.id,
        candidate_name: name,
        candidate_email: candidateEmail(),
      });

    const active = await mkApp(`E2E Активный ${stamp()}`);
    const rejected = await mkApp(`E2E Отказ ${stamp()}`);
    const hired = await mkApp(`E2E Нанят ${stamp()}`);

    await request.post(`${API}/applications/${rejected.id}/status`, {
      ...ctx,
      data: { status: "rejected" },
    });
    await request.post(`${API}/applications/${hired.id}/status`, {
      ...ctx,
      data: { status: "hired" },
    });

    const archive = await ok(request, `${API}/applications/archive/`, ctx);
    const ids = archive.applications.map((a: any) => a.id);
    expect(ids).toContain(rejected.id);
    expect(ids).toContain(hired.id);
    expect(ids, "отклик в работе не архивный").not.toContain(active.id);

    // Вторая половина страницы — документы; форма ответа обязана быть.
    expect(Array.isArray(archive.documents)).toBeTruthy();
  });
});

// ───────────────────────── 6. Документы ───────────────────────────────

test.describe("HR: документы", () => {
  test("документ заводится, виден в списке и в карточке сотрудника", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    const doc = await created(request, `${API}/documents/`, ctx, {
      employee_id: employee.id,
      title: `E2E договор ${stamp()}`,
      doc_type: "contract",
      file_path: `/docs/e2e-${stamp()}.pdf`,
      file_size: 2048,
      mime_type: "application/pdf",
      metadata: { source: "e2e" },
      // uploaded_by — FK на Employee, а не на пользователя.
      uploaded_by: employee.id,
    });
    expect(doc.metadata).toEqual({ source: "e2e" });

    const list = await ok(request, `${API}/documents/`, ctx);
    expect(list.items.map((d: any) => d.id)).toContain(doc.id);

    const ofEmployee = await ok(
      request,
      `${API}/employees/${employee.id}/documents`,
      ctx,
    );
    expect(ofEmployee.map((d: any) => d.id)).toEqual([doc.id]);

    expect(
      (await request.delete(`${API}/documents/${doc.id}`, ctx)).status(),
    ).toBeLessThan(300);
    expect(
      (await request.get(`${API}/documents/${doc.id}`, ctx)).status(),
    ).toBe(404);
  });

  test("нулевой размер файла не принимается", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const resp = await request.post(`${API}/documents/`, {
      ...ctx,
      data: {
        employee_id: employee.id,
        title: "Пустышка",
        doc_type: "contract",
        file_path: "/docs/empty.pdf",
        file_size: 0,
        uploaded_by: employee.id,
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("документы-блобы: создание, фильтр и удаление", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    const blob = await created(request, `${API}/mongo-documents/`, ctx, {
      sql_employee_id: employee.id,
      title: `E2E приказ ${stamp()}`,
      doc_type: "order",
      content: "Текст приказа",
      tags: ["e2e"],
      metadata: { kind: "test" },
    });
    expect(blob.id).toBeTruthy();
    expect(blob.tags).toEqual(["e2e"]);

    const filtered = await ok(
      request,
      `${API}/mongo-documents/?employee_id=${employee.id}`,
      ctx,
    );
    expect(filtered.map((d: any) => d.id)).toContain(blob.id);

    // Не-числовой идентификатор — 400 (битый id), а не 404.
    expect(
      (await request.get(`${API}/mongo-documents/not-an-id`, ctx)).status(),
    ).toBe(400);

    expect(
      (await request.delete(`${API}/mongo-documents/${blob.id}`, ctx)).status(),
    ).toBeLessThan(300);
  });
});

// ──────────────────── 7. Кадровая история ─────────────────────────────

test.describe("HR: кадровая история", () => {
  test("событие перевода резолвит названия отделов и должностей", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const from = await makePerson(request, ctx);
    const to = await makePerson(request, ctx);

    const event = await created(request, `${API}/personnel-history/`, ctx, {
      employee: from.employee.id,
      event_type: "transfer",
      event_date: today(),
      from_department: from.dept.id,
      to_department: to.dept.id,
      from_position: from.position.id,
      to_position: to.position.id,
      order_number: `ПР-${stamp()}`,
      comment: "E2E перевод",
    });

    // Смысл сериализатора: клиент не должен джойнить справочники сам —
    // на этом строится колонка «Детали» в таблице.
    expect(event.employee_name).toContain("Модулев");
    expect(event.from_department_name).toBe(from.dept.name);
    expect(event.to_department_name).toBe(to.dept.name);
    expect(event.from_position_title).toBe(from.position.title);
    expect(event.to_position_title).toBe(to.position.title);

    const list = await ok(request, `${API}/personnel-history/`, ctx);
    expect(list.map((e: any) => e.id)).toContain(event.id);

    expect(
      (await request.delete(`${API}/personnel-history/${event.id}`, ctx)).status(),
    ).toBeLessThan(300);
  });

  test("неизвестный тип события отбивается 400", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const resp = await request.post(`${API}/personnel-history/`, {
      ...ctx,
      data: {
        employee: employee.id,
        event_type: "teleported",
        event_date: today(),
      },
    });
    expect(resp.status()).toBe(400);
    expect((await resp.json()).detail).toContain("event_type must be one of");
  });

  test("событие правится и исчезает после удаления", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee, dept, position } = await makePerson(request, ctx);
    const event = await created(request, `${API}/personnel-history/`, ctx, {
      employee: employee.id,
      event_type: "hired",
      event_date: today(),
      to_department: dept.id,
      to_position: position.id,
      order_number: `ПР-${stamp()}`,
    });

    const updated = await request.put(
      `${API}/personnel-history/${event.id}/`,
      {
        ...ctx,
        data: {
          employee: employee.id,
          event_type: "promotion",
          event_date: today(),
          to_department: dept.id,
          to_position: position.id,
          order_number: event.order_number,
          comment: "повышение",
        },
      },
    );
    expect(updated.status(), await updated.text()).toBe(200);
    expect((await updated.json()).event_type).toBe("promotion");

    await request.delete(`${API}/personnel-history/${event.id}`, ctx);
    // Одиночного GET у события нет (PUT/DELETE) — проверяем повторным
    // удалением и тем, что запись ушла из общего списка.
    expect(
      (await request.delete(`${API}/personnel-history/${event.id}`, ctx)).status(),
    ).toBe(404);
    const list = await ok(request, `${API}/personnel-history/`, ctx);
    expect(list.map((e: any) => e.id)).not.toContain(event.id);
  });
});

// ─────────────── 8. Производственный календарь ────────────────────────

test.describe("HR: производственный календарь", () => {
  test("праздник уменьшает число рабочих дней в периоде", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    // Год вперёд — чтобы не спорить с уже размеченным текущим годом.
    // Рабочий день не «назначаем» вручную, а СПРАШИВАЕМ у календаря: иначе
    // тест начнёт падать в тот год, где выбранное число попало на субботу.
    const year = new Date().getFullYear() + 1;
    const yearDaysBefore = await ok(request, `${API}/calendar/?year=${year}`, ctx);
    const workingDay = yearDaysBefore.find(
      (d: any) => d.day.startsWith(`${year}-03-`) && d.type === "working",
    );
    expect(workingDay, "в марте обязан быть хоть один рабочий день").toBeTruthy();
    const day = workingDay.day;
    const range = `start=${year}-03-01&end=${year}-03-31`;

    const before = await ok(
      request,
      `${API}/calendar/working-days?${range}`,
      ctx,
    );

    const put = await request.put(`${API}/calendar/${day}`, {
      ...ctx,
      data: { day_type: "holiday", norm_hours: 0, note: "E2E праздник" },
    });
    expect(put.status(), await put.text()).toBe(200);

    const after = await ok(
      request,
      `${API}/calendar/working-days?${range}`,
      ctx,
    );
    expect(after.working_days).toBe(before.working_days - 1);
    expect(Number(after.norm_hours)).toBeLessThan(Number(before.norm_hours));

    // Год отдаёт исключение отдельной строкой — из этого строится список
    // «Исключения года» на странице.
    const yearDays = await ok(request, `${API}/calendar/?year=${year}`, ctx);
    const marked = yearDays.find((d: any) => d.day === day);
    expect(marked.type).toBe("holiday");
    expect(marked.note).toBe("E2E праздник");

    // Убираем за собой — календарь общий для всей базы.
    await request.delete(`${API}/calendar/${day}`, ctx);
    const restored = await ok(
      request,
      `${API}/calendar/working-days?${range}`,
      ctx,
    );
    expect(restored.working_days).toBe(before.working_days);
  });

  test("сокращённый день считается рабочим, но с меньшей нормой", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const year = new Date().getFullYear() + 1;
    const day = `${year}-03-05`;
    const range = `start=${day}&end=${day}`;

    await request.put(`${API}/calendar/${day}`, {
      ...ctx,
      data: { day_type: "short", norm_hours: 7, note: "E2E сокращённый" },
    });
    const info = await ok(request, `${API}/calendar/working-days?${range}`, ctx);
    expect(info.working_days).toBe(1);
    expect(Number(info.norm_hours)).toBe(7);

    await request.delete(`${API}/calendar/${day}`, ctx);
  });

  test("недопустимый тип дня не принимается", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const year = new Date().getFullYear() + 1;
    const resp = await request.put(`${API}/calendar/${year}-03-07`, {
      ...ctx,
      data: { day_type: "праздничек", norm_hours: 0 },
    });
    expect(resp.status()).toBe(422);
  });

  test("шаблон недели: создание, назначение по умолчанию, защита от удаления", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const days: Record<string, any> = {};
    for (let i = 0; i < 7; i++) {
      days[String(i)] = i < 5
        ? { type: "working", hours: 8 }
        : { type: "weekend", hours: 0 };
    }

    const tmpl = await created(request, `${API}/calendar/templates/`, ctx, {
      name: `E2E пятидневка ${stamp()}`,
      days,
    });
    expect(tmpl.is_default).toBe(false);

    const madeDefault = await request.post(
      `${API}/calendar/templates/${tmpl.id}/default`,
      ctx,
    );
    expect(madeDefault.status(), await madeDefault.text()).toBe(200);

    // Дефолт ровно один — иначе резолюция дня стала бы неоднозначной.
    const all = await ok(request, `${API}/calendar/templates/`, ctx);
    expect(all.filter((t: any) => t.is_default).length).toBe(1);
    expect(all.find((t: any) => t.is_default).id).toBe(tmpl.id);

    // Дефолтный шаблон удалить нельзя — иначе календарь остался бы без базы.
    const refused = await request.delete(
      `${API}/calendar/templates/${tmpl.id}`,
      ctx,
    );
    expect(refused.status()).toBe(409);
  });

  test("шаблон недели требует все семь дней", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const resp = await request.post(`${API}/calendar/templates/`, {
      ...ctx,
      data: {
        name: "E2E огрызок",
        days: { "0": { type: "working", hours: 8 } },
      },
    });
    expect(resp.status()).toBe(422);
  });

  test("сменный график назначается сотруднику и вытесняет шаблон недели", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);

    const pattern = await created(
      request,
      `${API}/calendar/shift-patterns/`,
      ctx,
      {
        name: `E2E 2/2 ${stamp()}`,
        slots: [
          { type: "work", hours: 12 },
          { type: "work", hours: 12 },
          { type: "off", hours: 0 },
          { type: "off", hours: 0 },
        ],
        holidays_off: false,
      },
    );
    expect(pattern.slots.length).toBe(4);

    const year = new Date().getFullYear() + 1;
    const anchor = ymd(year, 4, 1);
    const assigned = await request.put(`${API}/employees/${employee.id}/shift`, {
      ...ctx,
      data: { shift_pattern_id: pattern.id, anchor_date: anchor },
    });
    expect(assigned.status(), await assigned.text()).toBeLessThan(300);

    // Цикл 2/2 от якоря: два рабочих по 12 часов, два выходных.
    const cal = await ok(
      request,
      `${API}/employees/${employee.id}/calendar?start=${anchor}&end=${ymd(year, 4, 4)}`,
      ctx,
    );
    expect(cal.length).toBe(4);
    expect(cal[0].type).toBe("working");
    expect(cal[0].hours).toBe(12);
    expect(cal[2].type).toBe("weekend");

    await request.delete(`${API}/employees/${employee.id}/shift`, ctx);
    await request.delete(`${API}/calendar/shift-patterns/${pattern.id}`, ctx);
  });

  test("персональный оверрайд дня побеждает общий календарь", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { employee } = await makePerson(request, ctx);
    const year = new Date().getFullYear() + 1;
    const day = ymd(year, 5, 6);

    // Каким этот день числится в общем календаре — запоминаем ДО правки,
    // чтобы проверить, что персональный оверрайд его не задел.
    const commonBefore = await ok(
      request,
      `${API}/calendar/working-days?start=${day}&end=${day}`,
      ctx,
    );

    // Словарь типов дня общий для всего календаря и отпуска не знает —
    // допустимы только working/short/weekend/holiday.
    const put = await request.put(
      `${API}/employees/${employee.id}/calendar/${day}`,
      { ...ctx, data: { day_type: "weekend", norm_hours: 0, note: "E2E личный выходной" } },
    );
    expect(put.status(), await put.text()).toBe(200);

    const cal = await ok(
      request,
      `${API}/employees/${employee.id}/calendar?start=${day}&end=${day}`,
      ctx,
    );
    expect(cal[0].type).toBe("weekend");
    expect(cal[0].hours).toBe(0);

    // Общий календарь при этом не тронут — персональный оверрайд живёт в
    // своей таблице и на нормо-часы компании не влияет.
    const commonAfter = await ok(
      request,
      `${API}/calendar/working-days?start=${day}&end=${day}`,
      ctx,
    );
    expect(commonAfter).toEqual(commonBefore);

    await request.delete(
      `${API}/employees/${employee.id}/calendar/${day}`,
      ctx,
    );
  });
});

// ────────────────── 9. Штатное расписание ─────────────────────────────

test.describe("HR: штатное расписание", () => {
  test("строка считает ФОТ и попадает в сводку", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);

    const before = await ok(request, `${API}/staffing/summary/`, ctx);

    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: position.id,
      department_id: dept.id,
      grade: 3,
      headcount: "2",
      salary: "500000",
      note: "E2E строка",
    });
    // ФОТ = ставки × оклад, и приходит СТРОКОЙ с двумя знаками — деньги
    // через float сюда не попадают.
    expect(line.fot).toBe("1000000.00");
    expect(line.headcount).toBe("2.00");

    const after = await ok(request, `${API}/staffing/summary/`, ctx);
    expect(Number(after.total_fot) - Number(before.total_fot)).toBe(1_000_000);
    expect(Number(after.total_budgeted) - Number(before.total_budgeted)).toBe(2);

    // Разрез по отделам обязан содержать наш отдел с той же суммой.
    const row = after.by_department.find((d: any) => d.department_id === dept.id);
    expect(row).toBeTruthy();
    expect(row.fot).toBe("1000000.00");
    expect(row.department_name).toBe(dept.name);

    await request.delete(`${API}/staffing/${line.id}`, ctx);
  });

  test("занятость: две ставки, один человек — одна вакансия", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position, employee } = await makePerson(request, ctx);
    expect(employee.id).toBeTruthy();

    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: position.id,
      department_id: dept.id,
      headcount: "2",
      salary: "300000",
    });

    const occupancy = await ok(request, `${API}/staffing/occupancy/`, ctx);
    const row = occupancy.find(
      (r: any) => r.position_id === position.id && r.department_id === dept.id,
    );
    expect(row, "строка занятости по нашей паре должность+отдел").toBeTruthy();
    expect(row.budgeted).toBe("2.00");
    expect(row.filled, "созданный сотрудник занимает ставку").toBe(1);
    expect(row.vacant).toBe("1.00");
    // Названия резолвятся сервером — иначе таблица показывала бы голые id.
    expect(row.position_title).toBe(position.title);
    expect(row.department_name).toBe(dept.name);

    await request.delete(`${API}/staffing/${line.id}`, ctx);
  });

  test("перезаполнение не даёт отрицательных вакансий", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    // Ещё двое на ту же должность и отдел — итого 3 человека на 1 ставку.
    for (let i = 0; i < 2; i++) {
      await created(request, `${API}/employees/`, ctx, {
        first_name: "Тест",
        last_name: `Переполнев${stamp()}`,
        email: `over${stamp()}${i}@htq.test`,
        hire_date: today(),
        department_id: dept.id,
        position_id: position.id,
      });
    }
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: position.id,
      department_id: dept.id,
      headcount: "1",
      salary: "100000",
    });

    const occupancy = await ok(request, `${API}/staffing/occupancy/`, ctx);
    const row = occupancy.find(
      (r: any) => r.position_id === position.id && r.department_id === dept.id,
    );
    expect(row.filled).toBe(3);
    expect(row.vacant, "вакансии не уходят в минус").toBe("0.00");

    await request.delete(`${API}/staffing/${line.id}`, ctx);
  });

  test("ссылка на несуществующую должность отбивается", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept } = await makePerson(request, ctx);
    const resp = await request.post(`${API}/staffing/`, {
      ...ctx,
      data: { position_id: 999999, department_id: dept.id, headcount: "1", salary: "1" },
    });
    expect(resp.status()).toBe(422);
    expect((await resp.json()).detail).toContain("Position not found");
  });

  test("правка строки пересчитывает ФОТ, удаление убирает её из сводки", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makePerson(request, ctx);
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: position.id,
      department_id: dept.id,
      headcount: "1",
      salary: "100000",
    });

    // Здесь только PUT и только ПОЛНЫМ телом: отдельной Update-схемы у
    // раздела нет, StaffingLineIn обслуживает и создание, и правку.
    const patched = await request.put(`${API}/staffing/${line.id}`, {
      ...ctx,
      data: {
        position_id: position.id,
        department_id: dept.id,
        salary: "250000",
        headcount: "3",
      },
    });
    expect(patched.status(), await patched.text()).toBe(200);
    expect((await patched.json()).fot).toBe("750000.00");

    await request.delete(`${API}/staffing/${line.id}`, ctx);
    const lines = await ok(request, `${API}/staffing/`, ctx);
    expect(lines.map((l: any) => l.id)).not.toContain(line.id);
    expect(
      (await request.delete(`${API}/staffing/${line.id}`, ctx)).status(),
    ).toBe(404);
  });
});
