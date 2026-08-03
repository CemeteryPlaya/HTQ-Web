/**
 * Должности и уровни — интерактивный сценарий HR в браузере.
 *
 * Гонять против dev-сервера Vite и ЛОКАЛЬНОЙ базы (как 18_hr_ui и 20_hr_modules_ui).
 *
 * Чем отличается от соседей: 18_hr_ui только открывает `/hr/positions` и
 * проверяет, что страница ожила, а 17_hr_api дёргает эндпоинты мимо интерфейса.
 * Путь, которым реально ходит кадровик — завести уровень, потом должность на
 * этом уровне — до сих пор не проверял никто.
 *
 * Проверяется главное после ревью:
 *   * уровень заводится БЕЗ диапазона весов (его подбирает сервер);
 *   * в карточке должности есть «Уровень», а «Вес» убран в «Служебное»;
 *   * ошибка сервера видна пользователю, а не теряется молча.
 *
 * Тест убирает за собой и должность, и уровень.
 */
import { test, expect, ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures";
import type { Page } from "@playwright/test";

// Метка прогона в названиях: спека не должна падать из-за мусора, оставленного
// предыдущим запуском. Номер уровня заведомо далёкий от боевых.
const STAMP = Date.now().toString().slice(-6);
const LEVEL_NUMBER = 87;
const LEVEL_LABEL = `E2E уровень ${STAMP}`;
const POSITION_TITLE = `E2E должность ${STAMP}`;

async function login(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("i18nextLng", "ru");
  });
  await page.goto("/login");
  const password = page.locator('input[type="password"]').first();
  await expect(password).toBeVisible({ timeout: 30_000 });
  await page.locator('input[type="text"]').first().fill(ADMIN_EMAIL);
  await password.fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
}

/** Токен из localStorage — тем же перебором, что и 20_hr_modules_ui. */
async function accessToken(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    for (const key of Object.keys(window.localStorage)) {
      const raw = window.localStorage.getItem(key) ?? "";
      if (raw.startsWith("eyJ")) return raw;
      try {
        const parsed = JSON.parse(raw);
        if (parsed?.access) return parsed.access as string;
      } catch { /* не JSON — идём дальше */ }
    }
    return null;
  });
}

/** Удаляет за собой через API — UI-удаление зависит от window.confirm. */
async function cleanup(page: Page) {
  const token = await accessToken(page);
  if (!token) return;
  const headers = { Authorization: `Bearer ${token}` };

  const list = await page.request.get("/api/hr/v1/positions/?limit=200", { headers });
  if (list.ok()) {
    const body = await list.json();
    const items = Array.isArray(body) ? body : body.items ?? [];
    for (const item of items) {
      if (item.title === POSITION_TITLE) {
        await page.request.delete(`/api/hr/v1/positions/${item.id}/`, { headers });
      }
    }
  }
  await page.request.delete(`/api/hr/v1/positions/levels/${LEVEL_NUMBER}`, { headers });
}

test.describe("HR: должности и уровни", () => {
  test.afterEach(async ({ page }) => {
    await cleanup(page);
  });

  test("уровень заводится без диапазона весов и принимает должность", async ({ page }) => {
    await login(page);
    await cleanup(page);   // на случай мусора от упавшего прогона

    // ── вкладка «Уровни»: у HR спрашивают только номер, название и цвет ───
    await page.goto("/hr/positions?tab=levels");
    await expect(page.getByText(/чем меньше номер/i)).toBeVisible({ timeout: 30_000 });

    const numberField = page.getByLabel("Номер уровня");
    const labelField = page.getByLabel("Название уровня");
    await expect(numberField).toBeVisible();
    await expect(labelField).toBeVisible();
    // Полей диапазона в форме создания быть не должно — ради этого всё и затевалось.
    await expect(page.getByPlaceholder("От")).toHaveCount(0);
    await expect(page.getByPlaceholder("До")).toHaveCount(0);

    await numberField.fill(String(LEVEL_NUMBER));
    await labelField.fill(LEVEL_LABEL);
    await page.getByRole("button", { name: /добавить/i }).click();

    // Строка появилась.
    await expect(page.getByText(`L${LEVEL_NUMBER}`, { exact: true }).first())
      .toBeVisible({ timeout: 20_000 });

    // Диапазон проставил сервер — проверяем по данным, а не по вёрстке.
    const token = await accessToken(page);
    const levels = await page.request.get("/api/hr/v1/positions/levels/", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const created = (await levels.json()).find(
      (l: { level_number: number }) => l.level_number === LEVEL_NUMBER,
    );
    expect(created, "уровень должен создаться").toBeTruthy();
    expect(typeof created.weight_from).toBe("number");
    expect(created.weight_to).toBeGreaterThanOrEqual(created.weight_from);

    // ── повторный номер: ошибка обязана быть ВИДНА ───────────────────────
    await numberField.fill(String(LEVEL_NUMBER));
    await page.getByRole("button", { name: /добавить/i }).click();
    await expect(page.getByText(/already exists|уже существует|нет свободных весов/i).first())
      .toBeVisible({ timeout: 20_000 });

    // ── вкладка «Должности»: создать должность на этом уровне ────────────
    await page.getByRole("tab", { name: /должности/i }).click();
    await page.getByRole("button", { name: /создать должность/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // Вес спрятан: поле есть, но внутри свёрнутого «Служебное».
    await expect(dialog.getByText(/служебное/i)).toBeVisible();

    await dialog.getByRole("textbox").first().fill(POSITION_TITLE);

    // Radix SelectTrigger имеет role=combobox. Порядок в диалоге:
    // 0 — Отдел, 1 — Уровень, 2 — Уровень HR-доступа.
    await dialog.getByRole("combobox").nth(0).click();
    await page.getByRole("option").first().click();

    await dialog.getByRole("combobox").nth(1).click();
    await page.getByRole("option", { name: new RegExp(`L${LEVEL_NUMBER}`) }).click();

    await dialog.getByRole("button", { name: /^сохранить$/i }).click();
    await expect(dialog).toBeHidden({ timeout: 20_000 });

    // ── карточка встала в колонку своего уровня ──────────────────────────
    const column = page.locator("section").filter({ hasText: LEVEL_LABEL });
    await expect(column.getByText(POSITION_TITLE)).toBeVisible({ timeout: 20_000 });
    // На карточке — грейд, внутреннего веса нет.
    await expect(column.getByText(/грейд/i).first()).toBeVisible();
  });
});
