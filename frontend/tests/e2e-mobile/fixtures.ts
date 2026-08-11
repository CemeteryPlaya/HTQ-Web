/**
 * Фикстуры мобильного набора.
 *
 * Логин делаем через API и кладём токены в `localStorage` до загрузки
 * приложения (`addInitScript`), а не прогоняем форму входа в каждом тесте:
 * предмет проверки — вёрстка рабочих экранов, и лишний UI-шаг только добавил
 * бы поводов для ложных падений.
 */
import { test as base, request, type Page } from '@playwright/test';

const ADMIN_LOGIN = process.env.E2E_ADMIN_LOGIN || 'admin';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'admin12345';
const API_BASE = process.env.E2E_API_BASE || 'http://localhost:3000';

export interface Tokens {
  access: string;
  refresh: string;
}

export async function fetchTokens(): Promise<Tokens> {
  const ctx = await request.newContext({ baseURL: API_BASE });
  const resp = await ctx.post('/api/users/v1/token/', {
    data: { email: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  if (!resp.ok()) {
    throw new Error(
      `Не удалось получить токен (${resp.status()}). Проверьте, что backend поднят ` +
        `и учётка ${ADMIN_LOGIN} существует: ${await resp.text()}`,
    );
  }
  const json = await resp.json();
  await ctx.dispose();
  return { access: json.access, refresh: json.refresh };
}

/** Ключи те же, что использует приложение (`src/lib/auth/profileStorage.ts`). */
export async function applyTokens(page: Page, tokens: Tokens): Promise<void> {
  await page.addInitScript(
    ({ access, refresh }) => {
      window.localStorage.setItem('access', access);
      window.localStorage.setItem('refresh', refresh);
    },
    tokens,
  );
}

type Fixtures = {
  tokens: Tokens;
  authedPage: Page;
};

/*
 * `use` здесь — колбэк фикстуры Playwright, а не React-хук, и пустая
 * деструктуризация `{}` — принятый в Playwright способ объявить фикстуру без
 * зависимостей. Оба правила eslint срабатывают ложно, поэтому глушим их
 * адресно на этом блоке.
 */
/* eslint-disable react-hooks/rules-of-hooks, no-empty-pattern */
export const test = base.extend<Fixtures>({
  // Один логин на весь worker — токен переиспользуется между тестами.
  tokens: async ({}, use) => {
    await use(await fetchTokens());
  },
  authedPage: async ({ page, tokens }, use) => {
    await applyTokens(page, tokens);
    await use(page);
  },
});
/* eslint-enable react-hooks/rules-of-hooks, no-empty-pattern */

export { expect } from '@playwright/test';
export { ADMIN_LOGIN, ADMIN_PASSWORD, API_BASE };
