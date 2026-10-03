/**
 * Блокировка входа по логину (A7.2, D-S7-3; этап 7 A, задача 7.8).
 *
 * Пять неверных паролей подряд закрывают вход на `AUTH_LOCKOUT_SECONDS` —
 * 429 `E-AUTH-LOCKED` + `Retry-After` даже при верном пароле, а форма входа
 * пишет, через сколько минут повторить. В compose блокировка по умолчанию
 * ВЫКЛЮЧЕНА (порог 0), поэтому спека запускается только явно:
 *
 *   AUTH_LOCKOUT_THRESHOLD=5 docker compose -f docker-compose.test-local.yml up -d --no-deps backend-web
 *   E2E_LOCKOUT=1 npx playwright test tests/e2e/36_login_lockout.spec.ts --project=chromium
 *
 * Запросы к выдаче токена — без заголовка компании (голый домен): блокировка
 * считается по логину, а членство пользователя в пилотной компании для неё
 * не нужно. Форма — на хосте пилота: отказ блокировки приходит раньше
 * проверки членства.
 *
 * Пользователь — отдельный (не из ролей сценариев SC): блокировка снимается
 * в `afterAll` командой `auth_unlock`, но упавший посреди прогон оставил бы
 * роль сценария закрытой на 15 минут. Команда снятия — `E2E_UNLOCK_CMD`
 * (по умолчанию `docker exec` в `backend-web` стенда test-local).
 */
import { execFileSync } from "node:child_process";

import { request as pwRequest } from "@playwright/test";

import { BPP_API, BPP_BASE, PASSWORD, expect, test } from "./bpp_fixtures";

const LOGIN = process.env.E2E_LOCKOUT_USER || "petrov.i@htq.kz";
const THRESHOLD = Number(process.env.E2E_LOCKOUT_THRESHOLD || 5);
const UNLOCK = process.env.E2E_UNLOCK_CMD
  || "docker exec htqweb-local-backend-web-1 python manage.py auth_unlock";

test.skip(process.env.E2E_LOCKOUT !== "1",
  "блокировка входа на стенде выключена (порог 0) — см. шапку файла");

function unlock(): void {
  // Без оболочки: команда и логин — отдельные аргументы.
  const [command, ...args] = UNLOCK.split(/\s+/);
  execFileSync(command, [...args, LOGIN], { stdio: "pipe" });
}

test.describe.serial("блокировка входа", () => {
  test.beforeAll(() => unlock()); // прошлый упавший прогон не мешает
  test.afterAll(() => unlock());

  test("пять неверных паролей закрывают вход даже с верным паролем", async () => {
    const api = await pwRequest.newContext({ baseURL: BPP_API });
    for (let i = 0; i < THRESHOLD; i += 1) {
      const wrong = await api.post("/api/users/v1/token/", {
        data: { email: LOGIN, password: `wrong-${i}` },
      });
      expect(wrong.status(), `попытка ${i + 1}`).toBe(401);
    }

    const locked = await api.post("/api/users/v1/token/", {
      data: { email: LOGIN, password: PASSWORD },
    });
    expect(locked.status()).toBe(429);
    expect((await locked.json()).code).toBe("E-AUTH-LOCKED");
    expect(Number(locked.headers()["retry-after"])).toBeGreaterThan(0);
    await api.dispose();
  });

  test("форма входа называет минуты ожидания", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: BPP_BASE });
    await context.addInitScript(() => window.localStorage.setItem("i18nextLng", "ru"));
    const page = await context.newPage();
    await page.goto("/login");
    const password = page.locator('input[type="password"]').first();
    await expect(password).toBeVisible({ timeout: 30_000 });
    await page.locator('input[type="text"]').first().fill(LOGIN);
    await password.fill(PASSWORD);
    await page.locator('button[type="submit"]').first().click();

    await expect(page.getByText(/Слишком много неудачных попыток входа\. Повторите через \d+ мин\./))
      .toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/login/);
    await context.close();
  });

  test("auth_unlock снимает блокировку — вход снова проходит", async () => {
    unlock();
    const api = await pwRequest.newContext({ baseURL: BPP_API });
    const ok = await api.post("/api/users/v1/token/", {
      data: { email: LOGIN, password: PASSWORD },
    });
    expect(ok.status()).toBe(200);
    expect((await ok.json()).access).toBeTruthy();
    await api.dispose();
  });
});
