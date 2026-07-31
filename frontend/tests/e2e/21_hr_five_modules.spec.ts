/**
 * HR — углублённые тесты пяти разделов: штатное расписание,
 * производственный календарь, документы, архив, учёт времени.
 *
 * Гонять только против ЛОКАЛЬНОЙ базы.
 *
 * ВАЖНОЕ ОТЛИЧИЕ от 17/19/20: эта спека НЕ ЗАВОДИТ сотрудников, отделы и
 * должности. Она берёт уже засеянных (`manage.py seed_hr_demo`) и убирает
 * за собой всё, что создала сама. Причина простая: прошлые прогоны
 * оставили в базе полторы сотни «Модулев…»/«E2E отдел…», и справочники
 * стало невозможно читать глазами. Единственные создаваемые здесь
 * сущности — записи времени, документы, строки штатного расписания и
 * пометки календаря; у всех есть DELETE, и он вызывается в finally.
 *
 * Если сотрудников всё же надо завести (17/19/20 это делают), после
 * прогона чистить командой:
 *   DB_HOST=localhost DB_PORT=55432 python manage.py seed_hr_demo --purge-e2e
 */
import { test, expect } from "./fixtures";

const API = "/api/hr/v1";
const stamp = () => Date.now() + Math.floor(Math.random() * 10000);

/** Дата строкой без часовых поясов — `new Date(...).toISOString()` считает
 *  от локальной полуночи и в UTC+N съезжает на сутки назад. */
const ymd = (y: number, m: number, d: number) =>
  `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

type Ctx = { headers: Record<string, string> };
const auth = (t: string): Ctx => ({ headers: { Authorization: `Bearer ${t}` } });

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

/** Засеянный сотрудник — берём существующего вместо создания нового.
 *  Возвращаем и его отдел с должностью: штатному расписанию нужна пара
 *  (должность, отдел), и брать её у живого человека честнее, чем
 *  выдумывать. */
async function seededEmployee(request: any, ctx: Ctx) {
  const employees = await ok(request, `${API}/employees/?limit=200`, ctx);
  const list = Array.isArray(employees) ? employees : employees.items;
  const person = list.find(
    (e: any) => e.department_id && e.position_id && !e.is_deleted,
  );
  expect(
    person,
    "в базе нет ни одного засеянного сотрудника — сначала manage.py seed_hr_demo",
  ).toBeTruthy();
  return person;
}

// ══════════════════ 1. Штатное расписание ══════════════════

test.describe("Штатное расписание", () => {
  test("ФОТ считается как ставки × оклад и приходит строкой", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: person.position_id,
      department_id: person.department_id,
      grade: 3,
      headcount: "2.5",
      salary: "400000.50",
      note: `тест ${stamp()}`,
    });
    try {
      // Деньги везде строками с двумя знаками — через float такие суммы
      // округлялись бы по-разному в разных местах отчёта.
      expect(typeof line.fot).toBe("string");
      expect(line.headcount).toBe("2.50");
      expect(line.salary).toBe("400000.50");
      expect(line.fot).toBe("1000001.25"); // 2.5 × 400000.50
    } finally {
      await request.delete(`${API}/staffing/${line.id}`, ctx);
    }
  });

  test("сводка равна сумме своих же разрезов по отделам", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const lines: number[] = [];

    try {
      for (const salary of ["100000", "250000"]) {
        const line = await created(request, `${API}/staffing/`, ctx, {
          position_id: person.position_id,
          department_id: person.department_id,
          headcount: "1",
          salary,
        });
        lines.push(line.id);
      }

      const summary = await ok(request, `${API}/staffing/summary/`, ctx);
      // Итог обязан быть суммой разрезов — иначе шапка страницы и таблица
      // под ней показывают разные деньги.
      const sum = summary.by_department.reduce(
        (acc: number, d: any) => acc + Number(d.fot),
        0,
      );
      expect(Number(summary.total_fot)).toBeCloseTo(sum, 2);

      // Две строки одного отдела складываются в один разрез, а не в два.
      const rows = summary.by_department.filter(
        (d: any) => d.department_id === person.department_id,
      );
      expect(rows.length).toBe(1);
      expect(Number(rows[0].fot)).toBeGreaterThanOrEqual(350000);
    } finally {
      for (const id of lines) await request.delete(`${API}/staffing/${id}`, ctx);
    }
  });

  test("занятость сверяет бюджет ставок с живыми людьми", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    // Сколько людей реально сидит на этой паре (должность, отдел) —
    // спрашиваем, а не предполагаем: сид мог посадить туда нескольких.
    const employees = await ok(request, `${API}/employees/?limit=200`, ctx);
    const list = Array.isArray(employees) ? employees : employees.items;
    const headsOnPair = list.filter(
      (e: any) =>
        e.position_id === person.position_id &&
        e.department_id === person.department_id &&
        !e.is_deleted,
    ).length;

    const budget = headsOnPair + 2;
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: person.position_id,
      department_id: person.department_id,
      headcount: String(budget),
      salary: "300000",
    });
    try {
      const occupancy = await ok(request, `${API}/staffing/occupancy/`, ctx);
      const row = occupancy.find(
        (r: any) =>
          r.position_id === person.position_id &&
          r.department_id === person.department_id,
      );
      expect(row, "пара должность+отдел обязана быть в занятости").toBeTruthy();
      expect(Number(row.budgeted)).toBe(budget);
      expect(row.filled).toBe(headsOnPair);
      expect(Number(row.vacant)).toBe(2);
      // Названия резолвит сервер — таблица не должна показывать голые id.
      expect(row.position_title).toBeTruthy();
      expect(row.department_name).toBeTruthy();
    } finally {
      await request.delete(`${API}/staffing/${line.id}`, ctx);
    }
  });

  test("перезаполненная ставка не даёт отрицательных вакансий", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    // Бюджет заведомо меньше числа занятых — на этой паре человек есть.
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: person.position_id,
      department_id: person.department_id,
      headcount: "0.5",
      salary: "100000",
    });
    try {
      const occupancy = await ok(request, `${API}/staffing/occupancy/`, ctx);
      const row = occupancy.find(
        (r: any) =>
          r.position_id === person.position_id &&
          r.department_id === person.department_id,
      );
      expect(row.filled).toBeGreaterThanOrEqual(1);
      expect(row.vacant, "вакансии зажаты нулём снизу").toBe("0.00");
    } finally {
      await request.delete(`${API}/staffing/${line.id}`, ctx);
    }
  });

  test("фильтр по отделу отдаёт только его строки", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: person.position_id,
      department_id: person.department_id,
      headcount: "1",
      salary: "1000",
    });
    try {
      const filtered = await ok(
        request,
        `${API}/staffing/?department_id=${person.department_id}`,
        ctx,
      );
      expect(filtered.length).toBeGreaterThan(0);
      for (const row of filtered) {
        expect(row.department_id).toBe(person.department_id);
      }
      expect(filtered.map((l: any) => l.id)).toContain(line.id);
    } finally {
      await request.delete(`${API}/staffing/${line.id}`, ctx);
    }
  });

  test("битые ссылки на справочники отбиваются 422", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const badPosition = await request.post(`${API}/staffing/`, {
      ...ctx,
      data: {
        position_id: 999999,
        department_id: person.department_id,
        headcount: "1",
        salary: "1",
      },
    });
    expect(badPosition.status()).toBe(422);
    expect((await badPosition.json()).detail).toContain("Position not found");

    const badDept = await request.post(`${API}/staffing/`, {
      ...ctx,
      data: {
        position_id: person.position_id,
        department_id: 999999,
        headcount: "1",
        salary: "1",
      },
    });
    expect(badDept.status()).toBe(422);
    expect((await badDept.json()).detail).toContain("Department not found");
  });

  test("правка идёт полным телом через PUT и пересчитывает ФОТ", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const line = await created(request, `${API}/staffing/`, ctx, {
      position_id: person.position_id,
      department_id: person.department_id,
      headcount: "1",
      salary: "100000",
    });

    const updated = await request.put(`${API}/staffing/${line.id}`, {
      ...ctx,
      data: {
        position_id: person.position_id,
        department_id: person.department_id,
        headcount: "3",
        salary: "250000",
        grade: 5,
      },
    });
    expect(updated.status(), await updated.text()).toBe(200);
    const body = await updated.json();
    expect(body.fot).toBe("750000.00");
    expect(body.grade).toBe(5);

    // Удаление — и повторное удаление уже даёт 404.
    expect(
      (await request.delete(`${API}/staffing/${line.id}`, ctx)).status(),
    ).toBeLessThan(300);
    expect(
      (await request.delete(`${API}/staffing/${line.id}`, ctx)).status(),
    ).toBe(404);
  });
});

// ══════════════════ 2. Производственный календарь ══════════════════

test.describe("Производственный календарь", () => {
  /** Год вперёд — чтобы не спорить с уже размеченным текущим. */
  const YEAR = new Date().getFullYear() + 1;

  test("праздник убирает день из нормы, удаление возвращает", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const range = `start=${YEAR}-06-01&end=${YEAR}-06-30`;

    // Рабочий день не назначаем, а спрашиваем: иначе тест сломается в тот
    // год, где выбранное число попадёт на субботу.
    const year = await ok(request, `${API}/calendar/?year=${YEAR}`, ctx);
    const workday = year.find(
      (d: any) => d.day.startsWith(`${YEAR}-06-`) && d.type === "working",
    );
    expect(workday).toBeTruthy();

    const before = await ok(request, `${API}/calendar/working-days?${range}`, ctx);
    try {
      const put = await request.put(`${API}/calendar/${workday.day}`, {
        ...ctx,
        data: { day_type: "holiday", norm_hours: 0, note: "тест-праздник" },
      });
      expect(put.status(), await put.text()).toBe(200);

      const after = await ok(request, `${API}/calendar/working-days?${range}`, ctx);
      expect(after.working_days).toBe(before.working_days - 1);
      expect(Number(after.norm_hours)).toBe(
        Number(before.norm_hours) - workday.hours,
      );
    } finally {
      await request.delete(`${API}/calendar/${workday.day}`, ctx);
    }

    const restored = await ok(request, `${API}/calendar/working-days?${range}`, ctx);
    expect(restored).toEqual(before);
  });

  test("сокращённый день остаётся рабочим, но с меньшей нормой", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const day = ymd(YEAR, 6, 30);
    const range = `start=${day}&end=${day}`;
    try {
      await request.put(`${API}/calendar/${day}`, {
        ...ctx,
        data: { day_type: "short", norm_hours: 7, note: "предпраздничный" },
      });
      const info = await ok(request, `${API}/calendar/working-days?${range}`, ctx);
      expect(info.working_days).toBe(1);
      expect(Number(info.norm_hours)).toBe(7);
    } finally {
      await request.delete(`${API}/calendar/${day}`, ctx);
    }
  });

  test("выходной с ненулевыми часами всё равно не рабочий", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const day = ymd(YEAR, 6, 29);
    try {
      // Тип и часы — независимые поля; в норму попадает только пересечение
      // «тип рабочий И часов больше нуля».
      await request.put(`${API}/calendar/${day}`, {
        ...ctx,
        data: { day_type: "weekend", norm_hours: 8, note: "странный день" },
      });
      const info = await ok(
        request,
        `${API}/calendar/working-days?start=${day}&end=${day}`,
        ctx,
      );
      expect(info.working_days).toBe(0);
      expect(Number(info.norm_hours)).toBe(0);
    } finally {
      await request.delete(`${API}/calendar/${day}`, ctx);
    }
  });

  test("недопустимый тип дня не сохраняется", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const resp = await request.put(`${API}/calendar/${ymd(YEAR, 6, 28)}`, {
      ...ctx,
      data: { day_type: "отгул", norm_hours: 0 },
    });
    expect(resp.status()).toBe(422);
    expect(JSON.stringify(await resp.json())).toContain("day_type must be one of");
  });

  test("массовый импорт размечает сразу несколько дней", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const days = [ymd(YEAR, 7, 1), ymd(YEAR, 7, 2), ymd(YEAR, 7, 3)];
    try {
      // Тело импорта — голый массив, без конверта.
      const resp = await request.post(`${API}/calendar/import`, {
        ...ctx,
        data: days.map((day) => ({
          day,
          day_type: "holiday",
          norm_hours: 0,
          note: "импорт",
        })),
      });
      expect(resp.status(), await resp.text()).toBeLessThan(300);

      const info = await ok(
        request,
        `${API}/calendar/working-days?start=${days[0]}&end=${days[2]}`,
        ctx,
      );
      expect(info.working_days).toBe(0);
    } finally {
      for (const day of days) await request.delete(`${API}/calendar/${day}`, ctx);
    }
  });

  test("шаблон недели: ровно один дефолтный, дефолтный не удаляется", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const before = await ok(request, `${API}/calendar/templates/`, ctx);
    const previousDefault = before.find((t: any) => t.is_default);

    const days: Record<string, any> = {};
    for (let i = 0; i < 7; i++) {
      days[String(i)] =
        i < 5 ? { type: "working", hours: 8 } : { type: "weekend", hours: 0 };
    }
    const tmpl = await created(request, `${API}/calendar/templates/`, ctx, {
      name: `тест-пятидневка ${stamp()}`,
      days,
    });

    try {
      expect(tmpl.is_default).toBe(false);
      expect(
        (await request.post(`${API}/calendar/templates/${tmpl.id}/default`, ctx)).status(),
      ).toBe(200);

      const all = await ok(request, `${API}/calendar/templates/`, ctx);
      expect(
        all.filter((t: any) => t.is_default).length,
        "дефолт ровно один, иначе резолюция дня неоднозначна",
      ).toBe(1);

      // Дефолтный шаблон удалить нельзя — база осталась бы без основы.
      const refused = await request.delete(
        `${API}/calendar/templates/${tmpl.id}`,
        ctx,
      );
      expect(refused.status()).toBe(409);
    } finally {
      // Возвращаем прежний дефолт и убираем свой шаблон.
      if (previousDefault) {
        await request.post(
          `${API}/calendar/templates/${previousDefault.id}/default`,
          ctx,
        );
      }
      await request.delete(`${API}/calendar/templates/${tmpl.id}`, ctx);
    }
  });

  test("шаблон недели требует все семь дней", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const resp = await request.post(`${API}/calendar/templates/`, {
      ...ctx,
      data: { name: "огрызок", days: { "0": { type: "working", hours: 8 } } },
    });
    expect(resp.status()).toBe(422);
  });

  test("сменный график 2/2 разворачивается от даты привязки", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const pattern = await created(request, `${API}/calendar/shift-patterns/`, ctx, {
      name: `тест 2/2 ${stamp()}`,
      slots: [
        { type: "work", hours: 12 },
        { type: "work", hours: 12 },
        { type: "off", hours: 0 },
        { type: "off", hours: 0 },
      ],
      holidays_off: false,
    });
    const anchor = ymd(YEAR, 8, 1);

    try {
      const assigned = await request.put(`${API}/employees/${person.id}/shift`, {
        ...ctx,
        data: { shift_pattern_id: pattern.id, anchor_date: anchor },
      });
      expect(assigned.status(), await assigned.text()).toBeLessThan(300);

      // Восемь дней = два полных цикла, повторяющихся один в один.
      const cal = await ok(
        request,
        `${API}/employees/${person.id}/calendar?start=${anchor}&end=${ymd(YEAR, 8, 8)}`,
        ctx,
      );
      expect(cal.length).toBe(8);
      const types = cal.map((d: any) => d.type);
      expect(types).toEqual([
        "working", "working", "weekend", "weekend",
        "working", "working", "weekend", "weekend",
      ]);
      expect(cal[0].hours).toBe(12);
      expect(cal[2].hours).toBe(0);
    } finally {
      await request.delete(`${API}/employees/${person.id}/shift`, ctx);
      await request.delete(`${API}/calendar/shift-patterns/${pattern.id}`, ctx);
    }
  });

  test("персональный день перебивает смену и не трогает общий календарь", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const day = ymd(YEAR, 9, 15);

    const commonBefore = await ok(
      request,
      `${API}/calendar/working-days?start=${day}&end=${day}`,
      ctx,
    );

    try {
      const put = await request.put(
        `${API}/employees/${person.id}/calendar/${day}`,
        { ...ctx, data: { day_type: "weekend", norm_hours: 0, note: "личный" } },
      );
      expect(put.status(), await put.text()).toBe(200);

      const cal = await ok(
        request,
        `${API}/employees/${person.id}/calendar?start=${day}&end=${day}`,
        ctx,
      );
      expect(cal[0].type).toBe("weekend");
      expect(cal[0].note).toBe("личный");

      // Общая норма компании при этом не сдвинулась.
      const commonAfter = await ok(
        request,
        `${API}/calendar/working-days?start=${day}&end=${day}`,
        ctx,
      );
      expect(commonAfter).toEqual(commonBefore);
    } finally {
      await request.delete(`${API}/employees/${person.id}/calendar/${day}`, ctx);
    }
  });

  test("несуществующий шаблон и график дают 404", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    expect(
      (await request.delete(`${API}/calendar/templates/999999`, ctx)).status(),
    ).toBe(404);
    expect(
      (await request.delete(`${API}/calendar/shift-patterns/999999`, ctx)).status(),
    ).toBe(404);
    const bad = await request.put(`${API}/employees/${person.id}/shift`, {
      ...ctx,
      data: { shift_pattern_id: 999999, anchor_date: ymd(YEAR, 8, 1) },
    });
    expect(bad.status()).toBe(404);
  });
});

// ══════════════════ 3. Документы ══════════════════

test.describe("Документы", () => {
  test("документ создаётся, метаданные переживают круг", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const title = `тест-договор ${stamp()}`;

    const doc = await created(request, `${API}/documents/`, ctx, {
      employee_id: person.id,
      title,
      doc_type: "contract",
      file_path: `/docs/${stamp()}.pdf`,
      file_size: 4096,
      mime_type: "application/pdf",
      metadata: { number: "12/7", signed: true, tags: ["кадры", "договор"] },
      uploaded_by: person.id,
    });
    try {
      // Вложенный JSON должен вернуться ровно тем же — это поле хранит
      // произвольную структуру и не должно её уплощать.
      expect(doc.metadata).toEqual({
        number: "12/7",
        signed: true,
        tags: ["кадры", "договор"],
      });
      expect(doc.file_size).toBe(4096);
      expect(doc.uploaded_by).toBe(person.id);

      const single = await ok(request, `${API}/documents/${doc.id}`, ctx);
      expect(single.title).toBe(title);
    } finally {
      await request.delete(`${API}/documents/${doc.id}`, ctx);
    }
  });

  test("список отдаёт свежие сверху и считается постранично", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const ids: number[] = [];

    try {
      for (let i = 0; i < 3; i++) {
        const doc = await created(request, `${API}/documents/`, ctx, {
          employee_id: person.id,
          title: `тест-документ ${i} ${stamp()}`,
          doc_type: "order",
          file_path: `/docs/order-${stamp()}-${i}.pdf`,
          file_size: 100 + i,
          uploaded_by: person.id,
        });
        ids.push(doc.id);
      }

      const page = await ok(request, `${API}/documents/?page=1&limit=2`, ctx);
      expect(page.limit).toBe(2);
      expect(page.items.length).toBe(2);
      expect(page.total).toBeGreaterThanOrEqual(3);
      expect(page.pages).toBe(Math.ceil(page.total / 2));

      // Порядок — по убыванию даты создания: последний созданный первым.
      expect(page.items[0].id).toBe(ids[ids.length - 1]);
    } finally {
      for (const id of ids) await request.delete(`${API}/documents/${id}`, ctx);
    }
  });

  test("документы сотрудника отдаются его карточкой", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const before = await ok(
      request,
      `${API}/employees/${person.id}/documents`,
      ctx,
    );
    const doc = await created(request, `${API}/documents/`, ctx, {
      employee_id: person.id,
      title: `тест-справка ${stamp()}`,
      doc_type: "certificate",
      file_path: `/docs/cert-${stamp()}.pdf`,
      file_size: 512,
      uploaded_by: person.id,
    });
    try {
      const after = await ok(
        request,
        `${API}/employees/${person.id}/documents`,
        ctx,
      );
      expect(after.length).toBe(before.length + 1);
      expect(after.map((d: any) => d.id)).toContain(doc.id);
      for (const item of after) expect(item.employee_id).toBe(person.id);
    } finally {
      await request.delete(`${API}/documents/${doc.id}`, ctx);
    }
  });

  test("пустой файл и отсутствующие поля не проходят", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const zero = await request.post(`${API}/documents/`, {
      ...ctx,
      data: {
        employee_id: person.id,
        title: "пустышка",
        doc_type: "contract",
        file_path: "/docs/empty.pdf",
        file_size: 0,
        uploaded_by: person.id,
      },
    });
    expect(zero.status(), "размер файла обязан быть больше нуля").toBe(422);

    const noTitle = await request.post(`${API}/documents/`, {
      ...ctx,
      data: {
        employee_id: person.id,
        doc_type: "contract",
        file_path: "/docs/x.pdf",
        file_size: 10,
        uploaded_by: person.id,
      },
    });
    expect(noTitle.status()).toBe(422);
  });

  test("несуществующий документ — 404 на чтение и на удаление", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    expect((await request.get(`${API}/documents/999999`, ctx)).status()).toBe(404);
    expect(
      (await request.delete(`${API}/documents/999999`, ctx)).status(),
    ).toBe(404);
  });

  test("документы-блобы: фильтры, частичная правка, битый id", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);

    const blob = await created(request, `${API}/mongo-documents/`, ctx, {
      sql_employee_id: person.id,
      title: `тест-приказ ${stamp()}`,
      doc_type: "order",
      content: "Исходный текст",
      tags: ["тест"],
      metadata: { версия: 1 },
    });
    try {
      // Фильтр по типу и по сотруднику — то, чем пользуется страница.
      const byType = await ok(
        request,
        `${API}/mongo-documents/?doc_type=order&employee_id=${person.id}`,
        ctx,
      );
      expect(byType.map((d: any) => d.id)).toContain(blob.id);

      const byOther = await ok(
        request,
        `${API}/mongo-documents/?doc_type=contract&employee_id=${person.id}`,
        ctx,
      );
      expect(byOther.map((d: any) => d.id)).not.toContain(blob.id);

      // Частичная правка меняет только переданное поле.
      const patched = await request.patch(`${API}/mongo-documents/${blob.id}`, {
        ...ctx,
        data: { content: "Исправленный текст" },
      });
      expect(patched.status(), await patched.text()).toBe(200);
      const body = await patched.json();
      expect(body.content).toBe("Исправленный текст");
      expect(body.title, "заголовок не должен потеряться").toBe(blob.title);
      expect(body.tags).toEqual(["тест"]);

      // Не-числовой идентификатор — это битый id (400), а не «не найдено».
      expect(
        (await request.get(`${API}/mongo-documents/abc`, ctx)).status(),
      ).toBe(400);
      expect(
        (await request.get(`${API}/mongo-documents/999999`, ctx)).status(),
      ).toBe(404);
    } finally {
      await request.delete(`${API}/mongo-documents/${blob.id}`, ctx);
    }
  });
});

// ══════════════════ 4. Архив ══════════════════

test.describe("Архив", () => {
  /** Вакансия + отклики. Вакансию приходится завести — архив без неё
   *  проверить нечем; убираем в finally вместе с откликами. */
  async function withVacancy(
    request: any,
    ctx: Ctx,
    body: (vacancyId: number, appIds: number[]) => Promise<void>,
  ) {
    const person = await seededEmployee(request, ctx);
    const vacancy = await created(request, `${API}/vacancies/`, ctx, {
      title: `тест-вакансия ${stamp()}`,
      department_id: person.department_id,
      position_id: person.position_id,
    });
    const appIds: number[] = [];
    try {
      await body(vacancy.id, appIds);
    } finally {
      for (const id of appIds) await request.delete(`${API}/applications/${id}`, ctx);
      // Вакансия закрывается, а не удаляется — DELETE это мягкое закрытие.
      await request.delete(`${API}/vacancies/${vacancy.id}`, ctx);
    }
  }

  test("в архив попадают отказ и найм, отклик в работе — нет", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    await withVacancy(request, ctx, async (vacancyId, appIds) => {
      const mk = async (name: string) => {
        const app = await created(request, `${API}/applications/`, ctx, {
          vacancy_id: vacancyId,
          candidate_name: name,
          candidate_email: `arch${stamp()}@example.com`,
        });
        appIds.push(app.id);
        return app;
      };

      const active = await mk(`В работе ${stamp()}`);
      const rejected = await mk(`Отказ ${stamp()}`);
      const hired = await mk(`Нанят ${stamp()}`);

      for (const [id, status] of [
        [rejected.id, "rejected"],
        [hired.id, "hired"],
      ] as const) {
        const moved = await request.post(`${API}/applications/${id}/status`, {
          ...ctx,
          data: { status },
        });
        expect(moved.status()).toBe(200);
      }

      const archive = await ok(request, `${API}/applications/archive/`, ctx);
      const ids = archive.applications.map((a: any) => a.id);
      expect(ids).toContain(rejected.id);
      expect(ids).toContain(hired.id);
      expect(ids, "отклик в работе не архивный").not.toContain(active.id);
    });
  });

  test("промежуточные статусы воронки в архив не считаются", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    await withVacancy(request, ctx, async (vacancyId, appIds) => {
      // Архивными считаются только конечные состояния; всё, что ещё
      // движется по воронке, обязано остаться в работе.
      for (const status of ["reviewed", "interview", "offer"] as const) {
        const app = await created(request, `${API}/applications/`, ctx, {
          vacancy_id: vacancyId,
          candidate_name: `Воронка ${status} ${stamp()}`,
          candidate_email: `funnel${stamp()}@example.com`,
        });
        appIds.push(app.id);
        await request.post(`${API}/applications/${app.id}/status`, {
          ...ctx,
          data: { status },
        });
      }

      const archive = await ok(request, `${API}/applications/archive/`, ctx);
      const ids = archive.applications.map((a: any) => a.id);
      for (const id of appIds) expect(ids).not.toContain(id);
    });
  });

  test("архив отдаёт обе половины и свежие записи сверху", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const archive = await ok(request, `${API}/applications/archive/`, ctx);

    // Форма ответа — контракт страницы: два независимых списка.
    expect(Array.isArray(archive.applications)).toBeTruthy();
    expect(Array.isArray(archive.documents)).toBeTruthy();

    // Документы — верхние 200 по дате создания, сортировка по убыванию.
    expect(archive.documents.length).toBeLessThanOrEqual(200);
    const dates = archive.documents
      .map((d: any) => d.created_at)
      .filter(Boolean);
    const sorted = [...dates].sort().reverse();
    expect(dates).toEqual(sorted);

    // Каждая строка отклика несёт ровно тот набор полей, который рисует
    // таблица — лишнего в архиве быть не должно.
    for (const app of archive.applications.slice(0, 5)) {
      expect(Object.keys(app).sort()).toEqual(
        ["candidate_email", "candidate_name", "created_at", "id", "status", "vacancy_id"],
      );
    }
  });
});

// ══════════════════ 5. Учёт времени ══════════════════

test.describe("Учёт времени", () => {
  test("перерыв вычитается, отчёт за день сходится", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const day = ymd(new Date().getFullYear() + 1, 10, 5);

    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: person.id,
      date: day,
      start_time: "09:00:00",
      end_time: "18:00:00",
      break_minutes: 45,
      description: "тест-смена",
      project: "тест-проект",
    });
    try {
      const daily = await ok(
        request,
        `${API}/time-tracking/reports/daily?employee_id=${person.id}&date=${day}`,
        ctx,
      );
      // 9 часов минус 45 минут перерыва.
      expect(daily.total_minutes).toBe(9 * 60 - 45);
      expect(daily.entries.length).toBe(1);
      expect(daily.entries[0].project).toBe("тест-проект");
    } finally {
      await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx);
    }
  });

  test("перерыв длиннее смены не уводит норму в минус", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const day = ymd(new Date().getFullYear() + 1, 10, 6);

    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: person.id,
      date: day,
      start_time: "10:00:00",
      end_time: "11:00:00",
      break_minutes: 300, // пять часов перерыва на часовой смене
    });
    try {
      const daily = await ok(
        request,
        `${API}/time-tracking/reports/daily?employee_id=${person.id}&date=${day}`,
        ctx,
      );
      expect(daily.total_minutes, "минуты зажаты нулём снизу").toBe(0);
    } finally {
      await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx);
    }
  });

  test("неделя всегда семь ячеек, сумма сходится с итогом", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    // Понедельник заведомо будущей недели.
    const weekStart = ymd(new Date().getFullYear() + 1, 11, 1);
    const ids: number[] = [];

    try {
      for (const [offsetDay, hours] of [[1, 4], [3, 6]] as const) {
        const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
          employee_id: person.id,
          date: ymd(new Date().getFullYear() + 1, 11, offsetDay),
          start_time: "09:00:00",
          end_time: `${String(9 + hours).padStart(2, "0")}:00:00`,
        });
        ids.push(entry.id);
      }

      const weekly = await ok(
        request,
        `${API}/time-tracking/reports/weekly?employee_id=${person.id}&week_start=${weekStart}`,
        ctx,
      );
      expect(weekly.daily.length, "неделя — всегда 7 ячеек, даже пустых").toBe(7);
      expect(weekly.week_start).toBe(weekStart);
      expect(weekly.total_minutes).toBe((4 + 6) * 60);

      const sum = weekly.daily.reduce(
        (acc: number, d: any) => acc + d.total_minutes,
        0,
      );
      expect(sum, "итог недели обязан равняться сумме дней").toBe(
        weekly.total_minutes,
      );
      // Пустые дни присутствуют и честно показывают ноль.
      expect(weekly.daily.filter((d: any) => d.total_minutes === 0).length).toBe(5);
    } finally {
      for (const id of ids) {
        await request.delete(`${API}/time-tracking/entries/${id}`, ctx);
      }
    }
  });

  test("месяц группирует по неделям и не считает чужие записи", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const employees = await ok(request, `${API}/employees/?limit=200`, ctx);
    const list = Array.isArray(employees) ? employees : employees.items;
    const [mine, other] = list.filter((e: any) => !e.is_deleted);
    expect(other, "для проверки нужны двое засеянных сотрудников").toBeTruthy();

    const year = new Date().getFullYear() + 1;
    const ids: number[] = [];

    try {
      for (const [employee, day, hours] of [
        [mine, 3, 5],
        [mine, 17, 3],
        [other, 4, 8], // чужая запись — в наш отчёт попасть не должна
      ] as const) {
        const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
          employee_id: employee.id,
          date: ymd(year, 12, day),
          start_time: "09:00:00",
          end_time: `${String(9 + hours).padStart(2, "0")}:00:00`,
        });
        ids.push(entry.id);
      }

      const monthly = await ok(
        request,
        `${API}/time-tracking/reports/monthly?employee_id=${mine.id}&year=${year}&month=12`,
        ctx,
      );
      expect(monthly.year).toBe(year);
      expect(monthly.month).toBe(12);
      expect(monthly.total_minutes, "только свои 5 + 3 часа").toBe(8 * 60);
      expect(monthly.weekly.length, "две записи в разных неделях").toBe(2);
      for (const week of monthly.weekly) {
        expect(week.employee_id).toBe(mine.id);
      }
    } finally {
      for (const id of ids) {
        await request.delete(`${API}/time-tracking/entries/${id}`, ctx);
      }
    }
  });

  test("конец раньше или равен началу не сохраняется", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const day = ymd(new Date().getFullYear() + 1, 10, 7);

    for (const [start, end] of [
      ["18:00:00", "09:00:00"],
      ["12:00:00", "12:00:00"],
    ]) {
      const resp = await request.post(`${API}/time-tracking/entries/`, {
        ...ctx,
        data: {
          employee_id: person.id,
          date: day,
          start_time: start,
          end_time: end,
        },
      });
      expect(resp.status(), `${start} → ${end}`).toBe(422);
    }
  });

  test("правка записи пересчитывает отчёт", async ({ request, adminTokens }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const day = ymd(new Date().getFullYear() + 1, 10, 8);

    const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
      employee_id: person.id,
      date: day,
      start_time: "09:00:00",
      end_time: "17:00:00",
    });

    const patched = await request.patch(
      `${API}/time-tracking/entries/${entry.id}`,
      { ...ctx, data: { break_minutes: 30, description: "с перерывом" } },
    );
    expect(patched.status(), await patched.text()).toBe(200);

    const daily = await ok(
      request,
      `${API}/time-tracking/reports/daily?employee_id=${person.id}&date=${day}`,
      ctx,
    );
    expect(daily.total_minutes).toBe(8 * 60 - 30);
    expect(daily.entries[0].description).toBe("с перерывом");

    expect(
      (await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx)).status(),
    ).toBeLessThan(300);
    // Одиночного GET у записи нет — отсутствие проверяем повторным удалением.
    expect(
      (await request.delete(`${API}/time-tracking/entries/${entry.id}`, ctx)).status(),
    ).toBe(404);
  });

  test("список записей: свежие сверху, постранично", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const person = await seededEmployee(request, ctx);
    const year = new Date().getFullYear() + 1;
    const ids: number[] = [];

    try {
      for (const day of [10, 12, 14]) {
        const entry = await created(request, `${API}/time-tracking/entries/`, ctx, {
          employee_id: person.id,
          date: ymd(year, 10, day),
          start_time: "09:00:00",
          end_time: "10:00:00",
        });
        ids.push(entry.id);
      }

      const page = await ok(request, `${API}/time-tracking/entries/?page=1&limit=2`, ctx);
      expect(page.limit).toBe(2);
      expect(page.items.length).toBe(2);
      // Сортировка по убыванию даты — самый поздний день первым.
      expect(page.items[0].date >= page.items[1].date).toBeTruthy();
    } finally {
      for (const id of ids) {
        await request.delete(`${API}/time-tracking/entries/${id}`, ctx);
      }
    }
  });

  test("КОНТРАКТ: корень раздела отдаёт конверт, а не голый массив", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    const root = await ok(request, `${API}/time-tracking/`, ctx);

    // Фиксируем форму HTTP-ответа. Страница HRTimeTracking.tsx типизирует
    // его как массив, и это работает только потому, что axios-клиент
    // разворачивает конверт {items,total,page,pages,limit} интерцептором
    // (frontend/src/api/client.ts). Тест держит обе стороны: если конверт
    // на бэкенде изменят или разворачивание уберут — станет красным.
    expect(Array.isArray(root)).toBe(false);
    for (const key of ["items", "total", "page", "pages", "limit"]) {
      expect(root, `конверт обязан нести ${key}`).toHaveProperty(key);
    }
    expect(Array.isArray(root.items)).toBe(true);
  });

  test("ПРОБЕЛ: страница ходит в маршруты, которых нет", async ({
    request,
    adminTokens,
  }) => {
    const ctx = auth(adminTokens.access);
    // HRTimeTracking.tsx — страница про отпуска и отсутствия: у неё
    // leave_type, duration_days, approve/reject. Бэкенд же ведёт учёт
    // отработанных часов (date/start_time/end_time/break_minutes) и таких
    // маршрутов не предоставляет. Чтение «случайно» работает, запись — нет.
    //
    // Тест фиксирует РАЗМЕР расхождения, чтобы оно не потерялось: пока
    // раздел не сведут, эти четыре пути отвечают 404/405.
    const missing: Record<string, number> = {};
    for (const [method, path] of [
      ["POST", "/time-tracking/"],
      ["PUT", "/time-tracking/1/"],
      ["DELETE", "/time-tracking/1/"],
      ["POST", "/time-tracking/1/approve/"],
      ["POST", "/time-tracking/1/reject/"],
    ] as const) {
      const resp = await request.fetch(`${API}${path}`, {
        ...ctx,
        method,
        data: method === "POST" || method === "PUT" ? {} : undefined,
      });
      missing[`${method} ${path}`] = resp.status();
    }

    for (const [route, status] of Object.entries(missing)) {
      expect(
        [404, 405],
        `${route} -> ${status}: маршрут либо появился, либо форма ответа изменилась`,
      ).toContain(status);
    }
  });
});
