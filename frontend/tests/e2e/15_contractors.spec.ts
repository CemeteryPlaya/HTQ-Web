/**
 * Партнёры — сквозной проход по живому стеку.
 *
 * Гонять только против ЛОКАЛЬНОЙ базы (см. шапку 14_sites.spec.ts).
 *
 * Первый блок — самый важный: он держит границу «справочник есть, входа
 * нет». Пока партнёры не заходят в систему, `user_id` обязан оставаться
 * пустым, а уровень — не влиять на видимость. Когда вход будут включать,
 * эти тесты придётся менять осознанно, а не обнаружить их падение постфактум.
 */
import { test, expect } from "./fixtures";

const API = "/api/tasks/v1";
const stamp = () => Date.now() + Math.floor(Math.random() * 1000);

test.describe("Партнёры", () => {
  test("входа у партнёра нет: user_id не выставляется через API", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E ТОО ${stamp()}` },
      })
    ).json();

    // Пытаемся протащить user_id при создании — схема его не принимает.
    const created = await request.post(
      `${API}/contractors/${contractor.id}/workers/`,
      {
        headers: auth,
        data: {
          last_name: "Иванов",
          first_name: "Пётр",
          level: "senior",
          user_id: 999999,
        },
      },
    );
    expect(created.status()).toBe(201);
    const worker = await created.json();
    expect(worker.user_id).toBeNull();

    // И при обновлении тоже.
    const patched = await request.patch(
      `${API}/contractor-workers/${worker.id}/`,
      { headers: auth, data: { user_id: 999999 } },
    );
    expect(patched.status()).toBe(200);
    expect((await patched.json()).user_id).toBeNull();
  });

  test("уровень — свойство человека, а не организации", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E уровни ${stamp()}` },
      })
    ).json();

    for (const [last, level] of [
      ["Прорабов", "senior"],
      ["Рабочих", "junior"],
    ]) {
      await request.post(`${API}/contractors/${contractor.id}/workers/`, {
        headers: auth,
        data: { last_name: last, first_name: "Имя", level },
      });
    }

    const workers = await (
      await request.get(`${API}/contractors/${contractor.id}/workers/`, {
        headers: auth,
      })
    ).json();
    const levels = Object.fromEntries(
      workers.map((w: any) => [w.last_name, w.level]),
    );
    expect(levels).toEqual({ Прорабов: "senior", Рабочих: "junior" });
    // ФИО склеивается на бэкенде — страница показывает готовую строку.
    expect(workers[0].full_name).toContain("Имя");
  });

  test("БИН проверяется, а телефон принимает формат маски", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };

    const badBin = await request.post(`${API}/contractors/`, {
      headers: auth,
      data: { name: `E2E БИН ${stamp()}`, bin_iin: "12345" },
    });
    expect(badBin.status()).toBe(422);

    const ok = await request.post(`${API}/contractors/`, {
      headers: auth,
      data: {
        name: `E2E контакты ${stamp()}`,
        bin_iin: String(stamp()).padStart(12, "0").slice(0, 12),
        // Ровно то, что отдаёт PhoneInput.
        phone: "+7 (700) 483-55-81",
      },
    });
    expect(ok.status()).toBe(201);
    expect((await ok.json()).phone).toBe("+7 (700) 483-55-81");
  });

  test("организация с людьми архивируется, а не удаляется", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E занятая ${stamp()}` },
      })
    ).json();
    await request.post(`${API}/contractors/${contractor.id}/workers/`, {
      headers: auth,
      data: { last_name: "Сидоров", first_name: "Иван" },
    });

    const blocked = await request.delete(`${API}/contractors/${contractor.id}/`, {
      headers: auth,
    });
    expect(blocked.status()).toBe(409);
    expect((await blocked.json()).detail).toContain("архив");

    const archived = await request.patch(`${API}/contractors/${contractor.id}/`, {
      headers: auth,
      data: { status: "archived" },
    });
    expect((await archived.json()).status).toBe("archived");
  });

  test("человек отключается мягко и возвращается", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E мягко ${stamp()}` },
      })
    ).json();
    const worker = await (
      await request.post(`${API}/contractors/${contractor.id}/workers/`, {
        headers: auth,
        data: { last_name: "Отключаемый", first_name: "Пётр" },
      })
    ).json();

    expect(
      (await request.delete(`${API}/contractor-workers/${worker.id}/`, {
        headers: auth,
      })).status(),
    ).toBe(204);

    // Из списка по умолчанию исчез...
    const active = await (
      await request.get(`${API}/contractors/${contractor.id}/workers/`, {
        headers: auth,
      })
    ).json();
    expect(active.map((w: any) => w.id)).not.toContain(worker.id);

    // ...но строка на месте и возвращается.
    const all = await (
      await request.get(
        `${API}/contractors/${contractor.id}/workers/?active_only=false`,
        { headers: auth },
      )
    ).json();
    expect(all.map((w: any) => w.id)).toContain(worker.id);

    const restored = await request.patch(
      `${API}/contractor-workers/${worker.id}/`,
      { headers: auth, data: { is_active: true } },
    );
    expect((await restored.json()).is_active).toBe(true);
  });

  test("привлечение требует проект или объект и не дублируется", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E привлечение ${stamp()}` },
      })
    ).json();
    const site = await (
      await request.post(`${API}/sites/`, {
        headers: auth,
        data: { name: `E2E площадка ${stamp()}` },
      })
    ).json();

    const empty = await request.post(`${API}/contractor-engagements/`, {
      headers: auth,
      data: { contractor_id: contractor.id },
    });
    expect(empty.status()).toBe(422);

    const first = await request.post(`${API}/contractor-engagements/`, {
      headers: auth,
      data: { contractor_id: contractor.id, site_id: site.id, contract_no: "Д-1" },
    });
    expect(first.status()).toBe(201);
    expect((await first.json()).site_name).toBe(site.name);

    // Дубль отвергается ДАЖЕ при project_id = NULL — ради этого констрейнт
    // объявлен с nulls_distinct=False, иначе два NULL считались бы разными.
    const duplicate = await request.post(`${API}/contractor-engagements/`, {
      headers: auth,
      data: { contractor_id: contractor.id, site_id: site.id },
    });
    expect(duplicate.status()).toBe(500);
  });

  test("атрибуция задачи: партнёр и его человек видны в ответе", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E исполнитель ${stamp()}` },
      })
    ).json();
    const worker = await (
      await request.post(`${API}/contractors/${contractor.id}/workers/`, {
        headers: auth,
        data: { last_name: "Мастеров", first_name: "Иван" },
      })
    ).json();

    const task = await (
      await request.post(`${API}/tasks/`, {
        headers: auth,
        data: {
          summary: `E2E партнёрская задача ${stamp()}`,
          contractor_id: contractor.id,
          contractor_worker_id: worker.id,
        },
      })
    ).json();
    expect(task.contractor_name).toBe(contractor.name);
    expect(task.contractor_worker_name).toContain("Мастеров");

    // Фильтр по партнёру возвращает её.
    const filtered = await (
      await request.get(
        `${API}/tasks/?contractor_id=${contractor.id}&limit=200`,
        { headers: auth },
      )
    ).json();
    expect(filtered.map((t: any) => t.id)).toContain(task.id);

    // «Своя команда» — не возвращает: фильтры дополняют друг друга.
    const ownCrew = await (
      await request.get(`${API}/tasks/?own_crew=true&limit=200`, {
        headers: auth,
      })
    ).json();
    expect(ownCrew.map((t: any) => t.id)).not.toContain(task.id);
    expect(ownCrew.every((t: any) => t.contractor_id === null)).toBeTruthy();
  });

  test("техника партнёра обязана называть партнёра", async ({
    request,
    adminTokens,
  }) => {
    const auth = { Authorization: `Bearer ${adminTokens.access}` };
    const contractor = await (
      await request.post(`${API}/contractors/`, {
        headers: auth,
        data: { name: `E2E владелец ${stamp()}` },
      })
    ).json();

    const orphan = await request.post(`${API}/equipment/`, {
      headers: auth,
      data: { name: `E2E ничей кран ${stamp()}`, ownership: "contractor" },
    });
    expect(orphan.status()).toBe(422);

    const owned = await request.post(`${API}/equipment/`, {
      headers: auth,
      data: {
        name: `E2E кран ${stamp()}`,
        ownership: "contractor",
        contractor_id: contractor.id,
      },
    });
    expect(owned.status()).toBe(201);
    expect((await owned.json()).contractor_name).toBe(contractor.name);

    // Существующая техника читается как собственная, а не «неизвестно».
    const own = await request.post(`${API}/equipment/`, {
      headers: auth,
      data: { name: `E2E наш экскаватор ${stamp()}` },
    });
    expect((await own.json()).ownership).toBe("own");

    const byOwner = await (
      await request.get(`${API}/equipment/?contractor_id=${contractor.id}`, {
        headers: auth,
      })
    ).json();
    expect(
      byOwner.every((e: any) => e.contractor_id === contractor.id),
    ).toBeTruthy();
  });
});
