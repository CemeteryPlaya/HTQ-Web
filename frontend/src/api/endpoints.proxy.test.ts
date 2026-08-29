/**
 * Сторож на dev-прокси.
 *
 * У прод-nginx есть общий `location /api/` — он проксирует в бэкенд всё, чего
 * не поймали частные правила. У таблицы прокси Vite такого общего правила
 * НЕТ: она перечисляет префиксы поимённо. Домен, забытый в ней, ведёт себя
 * так: запрос уходит не в бэкенд, а в сам dev-сервер, тот отдаёт index.html,
 * клиент получает HTML вместо JSON — страница пуста, в консоли ошибка разбора,
 * и ни то, ни другое на причину не указывает. В проде при этом всё работает,
 * поэтому находится такое поздно и дорого.
 *
 * Ровно так и случилось с `access` при слиянии двух половин стадии 2.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { API_ENDPOINTS } from './endpoints';

const viteConfig = readFileSync(resolve(__dirname, '../../vite.config.ts'), 'utf-8');

/** Первый сегмент пути домена: 'access/v1' -> 'access'. */
const domainOf = (endpoint: string): string => endpoint.split('/')[0];

describe('таблица прокси dev-сервера', () => {
  it('покрывает каждый домен из API_ENDPOINTS', () => {
    const missing = Object.entries(API_ENDPOINTS)
      .map(([key, endpoint]) => [key, domainOf(endpoint)] as const)
      .filter(([, domain]) => !viteConfig.includes(`"^/api/${domain}/`))
      .map(([key, domain]) => `${key} → /api/${domain}/`);

    expect(missing).toEqual([]);
  });
});
