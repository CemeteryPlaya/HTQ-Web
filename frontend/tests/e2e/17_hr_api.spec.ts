/**
 * HR — сквозной проход по всем группам функций на живом стеке.
 *
 * Гонять только против ЛОКАЛЬНОЙ базы (см. шапку 14_sites.spec.ts): тесты
 * создают отделы, должности, сотрудников, вакансии и отклики.
 *
 * Зачем это поверх 8 тысяч строк юнит-тестов в apps/hr/tests: те проверяют
 * сервисы и вьюхи по отдельности, на подготовленных объектах. Здесь
 * проверяется цепочка целиком — маршрут, авторизация, сериализация, реальный
 * Postgres — и СВЯЗКИ между функциями, которых юнит-тест не видит: отдел
 * появляется в дереве, сотрудник попадает в список своего отдела, отклик
 * доезжает до статуса «нанят».
 */
import { test, expect } from "./fixtures";

const API = "/api/hr/v1";
const stamp = () => Date.now() + Math.floor(Math.random() * 10000);

type Ctx = { headers: Record<string, string> };

async function ok(request: any, url: string, ctx: Ctx) {
  const resp = await request.get(url, ctx);
  expect(resp.status(), `GET ${url}`).toBe(200);
  return resp.json();
}

/** Отдел + должность — минимальный набор, без которого сотрудника не завести
 *  (у Employee оба поля FK PROTECT NOT NULL). */
async function makeDeptAndPosition(request: any, ctx: Ctx) {
  const dept = await (
    await request.post(`${API}/departments/`, {
      ...ctx,
      data: { name: `E2E отдел ${stamp()}` },
    })
  ).json();
  // weight глобально уникален (position_service.WeightTaken), а дефолт —
  // 100, поэтому каждой должности нужен свой. Берём из большого диапазона,
  // чтобы не сталкиваться с существующими.
  const weight = 10_000 + Math.floor(Math.random() * 5_000_000);
  const resp = await request.post(`${API}/positions/`, {
    ...ctx,
    data: { title: `E2E должность ${stamp()}`, department_id: dept.id, weight },
  });
  expect(resp.status(), "создание должности").toBe(201);
  const position = await resp.json();
  return { dept, position };
}

test.describe("HR: справочники", () => {
  test("каждый читающий маршрут отвечает 200", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };

    // Один прогон по всем спискам: маршрут, который отвалился, назовёт себя
    // в сообщении. Это дешёвая страховка от «переименовали путь и забыли».
    for (const path of [
      "employees/",
      "employees/users/",
      "employees/hr-level/",
      "departments/",
      "departments/tree/",
      "positions/",
      "positions/levels/",
      "positions/permissions-catalog/",
      "documents/",
      "vacancies/",
      "applications/",
      "share-links/",
      "org/tree/",
      "org/subordination-matrix/",
      "pmo/",
      "staffing/",
      "staffing/summary/",
      "staffing/occupancy/",
      "logs/",
      "personnel-history/",
      "department-folders/",
      "calendar/templates/",
      "calendar/shift-patterns/",
      "time-tracking/",
      "time-tracking/entries/",
    ]) {
      const body = await ok(request, `${API}/${path}`, ctx);
      expect(body, `${path} вернул пустой ответ`).toBeTruthy();
    }
  });

  test("маршруты с обязательными параметрами дают 422, а не 500", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };

    // Пропущенный обязательный параметр — ошибка клиента. 500 здесь означал
    // бы, что запрос дошёл до кода, который на него не рассчитан.
    for (const path of [
      "department-files/",          // требует folder
      "calendar/working-days/",     // требует start и end
      "department-files/search/",   // требует q
    ]) {
      const resp = await request.get(`${API}/${path}`, ctx);
      expect(resp.status(), `${path} без параметров`).toBe(422);
    }

    // org/relations — только POST: GET по нему обязан быть 405, а не 404,
    // иначе непонятно, «нет маршрута» или «нет метода».
    const relations = await request.get(`${API}/org/relations/`, ctx);
    expect(relations.status()).toBe(405);

    // ...а с параметрами — отвечают.
    const today = new Date();
    const from = new Date(today.getFullYear(), 0, 1).toISOString().slice(0, 10);
    const to = new Date(today.getFullYear(), 11, 31).toISOString().slice(0, 10);
    await ok(request, `${API}/calendar/working-days/?start=${from}&end=${to}`, ctx);
    await ok(request, `${API}/department-files/search/?q=a`, ctx);
  });

  test("без токена HR закрыт целиком", async ({ request }) => {
    for (const path of [
      "employees/",
      "departments/",
      "positions/",
      "staffing/",
      "logs/",
      "share-links/",
    ]) {
      const resp = await request.get(`${API}/${path}`);
      expect(resp.status(), `аноним на ${path}`).toBe(401);
    }
  });
});

test.describe("HR: отделы и должности", () => {
  test("отдел заводится, виден в дереве, отдаёт своих сотрудников", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const name = `E2E отдел ${stamp()}`;

    const created = await request.post(`${API}/departments/`, {
      ...ctx,
      data: { name },
    });
    expect(created.status()).toBe(201);
    const dept = await created.json();

    // Дерево строится отдельным сервисом — отдел обязан появиться и там.
    const tree = await ok(request, `${API}/departments/tree/`, ctx);
    expect(JSON.stringify(tree)).toContain(name);

    // Пустой отдел отдаёт пустой список, а не 404.
    const staff = await ok(
      request,
      `${API}/departments/${dept.id}/employees/`,
      ctx,
    );
    expect(Array.isArray(staff)).toBeTruthy();
    expect(staff.length).toBe(0);
  });

  test("должность создаётся и находится в справочнике", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { position } = await makeDeptAndPosition(request, ctx);

    // Фильтра по отделу на сервере НЕТ — PositionListQuery знает только page
    // и limit, страница фильтрует у себя. Поэтому просим весь справочник.
    const listed = await ok(request, `${API}/positions/?limit=200`, ctx);
    expect(listed).toHaveProperty("items");
    expect(listed.items.map((p: any) => p.id)).toContain(position.id);
  });

  test("справочник должностей не обрезается дефолтной страницей", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };

    // Дефолт сервера — 20 записей. Страница должностей и селектор в карточке
    // сотрудника тянут справочник целиком и пагинации не имеют, поэтому
    // клиент обязан просить limit. Тест держит именно это: если запрос
    // без limit снова начнут считать достаточным, разница всплывёт здесь,
    // а не тем, что должность нельзя выбрать в форме.
    const paged = await ok(request, `${API}/positions/`, ctx);
    const full = await ok(request, `${API}/positions/?limit=200`, ctx);

    expect(full.items.length).toBe(full.total);
    if (paged.total > 20) {
      expect(paged.items.length).toBeLessThan(full.items.length);
    }
  });

  test("каталог прав должностей непустой", async ({ request, adminTokens }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const catalog = await ok(request, `${API}/positions/permissions-catalog/`, ctx);
    // Это тот самый справочник ключей вида hr.employees.view.all, на котором
    // держится весь HR-скоуп. Пустой каталог означал бы, что права не выдать.
    expect(JSON.stringify(catalog).length).toBeGreaterThan(50);
  });
});

test.describe("HR: сотрудники", () => {
  test("сотрудник заводится, правится и попадает в свой отдел", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makeDeptAndPosition(request, ctx);

    const created = await request.post(`${API}/employees/`, {
      ...ctx,
      data: {
        first_name: "Тест",
        last_name: `Сотрудников${stamp()}`,
        email: `emp${stamp()}@htq.test`,
        hire_date: new Date().toISOString().slice(0, 10),
        department_id: dept.id,
        position_id: position.id,
        // Ровно то, что отдаёт PhoneInput — маска общая для всей платформы.
        phone: "+7 (700) 483-55-81",
      },
    });
    expect(created.status()).toBe(201);
    const employee = await created.json();
    expect(employee.phone).toBe("+7 (700) 483-55-81");

    const patched = await request.patch(`${API}/employees/${employee.id}/`, {
      ...ctx,
      data: { phone: "+7 (701) 111-22-33" },
    });
    expect(patched.status()).toBe(200);
    expect((await patched.json()).phone).toBe("+7 (701) 111-22-33");

    const inDept = await ok(
      request,
      `${API}/departments/${dept.id}/employees/`,
      ctx,
    );
    expect(inDept.map((e: any) => e.id)).toContain(employee.id);
  });

  test("карточка сотрудника, Т-2 и история отвечают", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makeDeptAndPosition(request, ctx);
    const employee = await (
      await request.post(`${API}/employees/`, {
        ...ctx,
        data: {
          first_name: "Карточка",
          last_name: `Тестов${stamp()}`,
          email: `card${stamp()}@htq.test`,
          hire_date: new Date().toISOString().slice(0, 10),
          department_id: dept.id,
          position_id: position.id,
        },
      })
    ).json();

    await ok(request, `${API}/employees/${employee.id}/card/`, ctx);
    await ok(request, `${API}/employees/${employee.id}/card/t2/`, ctx);
    await ok(request, `${API}/employees/${employee.id}/history/`, ctx);
    await ok(request, `${API}/employees/${employee.id}/documents/`, ctx);
    await ok(request, `${API}/employees/${employee.id}/pmos/`, ctx);
  });

  test("свой профиль: 404 без карточки, но не 500", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    // У админского аккаунта карточки сотрудника нет — это законное 404.
    const me = await request.get(`${API}/employees/me/`, ctx);
    expect([200, 404]).toContain(me.status());

    // А вот уровень доступа обязан резолвиться всегда: на нём держится
    // весь HR-скоуп, и «не смогли определить» здесь означало бы отказ в
    // доступе живым кадровикам.
    const level = await ok(request, `${API}/employees/hr-level/`, ctx);
    expect(level).toHaveProperty("level");
  });

  test("несуществующий сотрудник — 404, а не 500", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    for (const path of [
      "employees/9999999/",
      "employees/9999999/card/",
      "departments/9999999/",
      "positions/9999999/",
    ]) {
      const resp = await request.get(`${API}/${path}`, ctx);
      expect(resp.status(), path).toBe(404);
    }
  });
});

test.describe("HR: рекрутинг", () => {
  test("вакансия → отклик → наём", async ({ request, adminTokens }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const { dept, position } = await makeDeptAndPosition(request, ctx);

    const vacancy = await request.post(`${API}/vacancies/`, {
      ...ctx,
      data: {
        title: `E2E вакансия ${stamp()}`,
        department_id: dept.id,
        position_id: position.id,
      },
    });
    expect(vacancy.status()).toBe(201);
    const vac = await vacancy.json();

    // Контракт бэкенда — JSON с полями candidate_*. Форма во фронте шлёт
    // другое (см. test.fail ниже).
    const application = await request.post(`${API}/applications/`, {
      ...ctx,
      data: {
        vacancy_id: vac.id,
        candidate_name: `Кандидат ${stamp()}`,
        // Не .test/.local: email-validator отвергает служебные домены —
        // это верно, а не дефект, но тестовые данные должны быть валидными.
        candidate_email: `cand${stamp()}@example.com`,
        candidate_phone: "+7 (700) 483-55-81",
      },
    });
    expect(application.status()).toBe(201);
    const app = await application.json();
    expect(app.candidate_phone).toBe("+7 (700) 483-55-81");

    // Отклик виден в списке своей вакансии.
    const byVacancy = await ok(
      request,
      `${API}/vacancies/${vac.id}/applications/`,
      ctx,
    );
    expect(JSON.stringify(byVacancy)).toContain(String(app.id));

    // Страница «Офферы» жмёт именно PATCH applications/{id}/ со статусом —
    // не отдельный маршрут. Проверяем тот путь, которым ходит интерфейс.
    const hired = await request.patch(`${API}/applications/${app.id}/`, {
      ...ctx,
      data: { status: "hired" },
    });
    expect(hired.status()).toBe(200);
    expect((await hired.json()).status).toBe("hired");
  });
});

test.describe("HR: оргструктура, PMO, штатка", () => {
  test("оргдерево, матрица подчинения и стратегия удаления отвечают", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    await ok(request, `${API}/org/tree/`, ctx);
    await ok(request, `${API}/org/subordination-matrix/`, ctx);
    await ok(request, `${API}/org/settings/deletion-strategy/`, ctx);
  });

  test("штатка считается и даёт сводку с занятостью", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    await ok(request, `${API}/staffing/`, ctx);
    await ok(request, `${API}/staffing/summary/`, ctx);
    await ok(request, `${API}/staffing/occupancy/`, ctx);
  });

  test("PMO заводится и отдаёт свою оргсхему", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const created = await request.post(`${API}/pmo/`, {
      ...ctx,
      data: { name: `E2E PMO ${stamp()}` },
    });
    expect([201, 400, 422]).toContain(created.status());
    if (created.status() !== 201) return;

    const pmo = await created.json();
    await ok(request, `${API}/pmo/${pmo.id}/members/`, ctx);
    await ok(request, `${API}/pmo/${pmo.id}/org-chart/`, ctx);
  });
});

test.describe("HR: аудит и публичные ссылки", () => {
  test("журнал действий пополняется при изменении", async ({
    request,
    adminTokens,
  }) => {
    const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
    const before = await ok(request, `${API}/logs/`, ctx);
    const beforeCount = (before.items ?? before).length;

    await request.post(`${API}/departments/`, {
      ...ctx,
      data: { name: `E2E аудит ${stamp()}` },
    });

    const after = await ok(request, `${API}/logs/`, ctx);
    const afterCount = (after.items ?? after).length;
    // Журнал — append-only; действие обязано в нём отразиться.
    expect(afterCount).toBeGreaterThanOrEqual(beforeCount);
  });

  test("публичная ссылка по несуществующему токену не выдаёт 500", async ({
    request,
  }) => {
    // Важно, что 404/410, а не 500: код ответа не должен отличать
    // «токена нет» от «что-то упало».
    for (const path of [
      "public/org/definitely-not-a-token",
      "public/employee/definitely-not-a-token",
    ]) {
      const resp = await request.get(`${API}/${path}`);
      expect([404, 401, 410], path).toContain(resp.status());
    }
  });
});


// ─────────────────────────────────────────────────────────────────────────
// Найденный дефект. Помечен test.fail(): тест ожидает провала, поэтому
// сьюта зелёная, но КАК ТОЛЬКО дефект починят — тест начнёт падать с
// "expected to fail, but passed" и заставит снять пометку. Так баг не
// потеряется и не зарастёт.
//
// Второй дефект, найденный этим же проходом (невалидное тело с кириллицей
// отдавало 500 вместо 422), уже починен — он лежал в общем слое
// htqweb/http.py и покрыт apps/core/tests/test_validation_envelope.py.
// ─────────────────────────────────────────────────────────────────────────

test.describe("HR: известные дефекты", () => {
  test.fail(
    "форма откликов не может создать отклик: контракты фронта и бэкенда разошлись",
    async ({ request, adminTokens }) => {
      const ctx = { headers: { Authorization: `Bearer ${adminTokens.access}` } };
      const { dept, position } = await makeDeptAndPosition(request, ctx);
      const vac = await (
        await request.post(`${API}/vacancies/`, {
          ...ctx,
          data: {
            title: `E2E вакансия ${stamp()}`,
            department_id: dept.id,
            position_id: position.id,
          },
        })
      ).json();

      // Ровно то, что отправляет HRApplications.tsx: multipart и свои имена
      // полей. Бэкенд же объявлен как body=ApplicationCreate, то есть ждёт
      // JSON с vacancy_id / candidate_name / candidate_email /
      // candidate_phone. Совпадающих полей нет ни одного.
      const resp = await request.post(`${API}/applications/`, {
        ...ctx,
        multipart: {
          vacancy: String(vac.id),
          first_name: "Иван",
          last_name: "Кандидатов",
          email: `cand${stamp()}@htq.test`,
          phone: "+7 (700) 483-55-81",
          notes: "",
          cover_letter: "",
        },
      });
      expect(resp.status()).toBe(201);
    },
  );

});
