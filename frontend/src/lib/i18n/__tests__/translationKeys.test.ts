/**
 * Заслон против сырых i18n-ключей в интерфейсе.
 *
 * Симптом всегда один: на экране вместо подписи стоит сам ключ —
 * «HR.NAV.GROUPS.PEOPLE» (капс добавляет CSS). Причин ровно две, и обе тихие:
 *
 *  1. Ключ вывели БЕЗ `t()`. Так было в `HRLayout`: карта `categoryTitles`
 *     объявлена на уровне модуля, где `t` из хука недоступен, и её значения
 *     уходили в разметку как есть. Лечится `translatedMap` — он переводит
 *     ключ на чтение.
 *  2. `t('ключ')` есть, а ключа в словаре нет. i18next в этом случае молча
 *     возвращает сам ключ: ни исключения, ни предупреждения в консоли.
 *
 * Этот тест закрывает вторую причину — единственную, которую можно проверить
 * статически и без догадок. Первая ловится ревью и приёмом `translatedMap`.
 *
 * Проверяем по `ru`, а не по `en`, потому что `fallbackLng: 'ru'`
 * (`src/i18n.js`): ключ, потерянный только в `en`, покажет русский текст —
 * некрасиво, но читаемо; потерянный в `ru` показывает сам ключ.
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../../../..');
const SRC = path.join(FRONTEND, 'src');

type Dict = Record<string, unknown>;

function flatten(obj: Dict, prefix = ''): Set<string> {
  const out = new Set<string>();
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix + k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const nested of flatten(v as Dict, key + '.')) out.add(nested);
    } else {
      out.add(key);
    }
  }
  return out;
}

function loadLocale(lng: string): Set<string> {
  const file = path.join(FRONTEND, 'public', 'locales', lng, 'translation.json');
  return flatten(JSON.parse(fs.readFileSync(file, 'utf-8')) as Dict);
}

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules' && entry.name !== '__tests__') sourceFiles(full, acc);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.(test|spec)\.(ts|tsx)$/.test(entry.name)) {
      acc.push(full);
    }
  }
  return acc;
}

/** Ключ i18n: точечный путь без слешей, пробелов и подстановок. */
const KEYISH = /^[a-z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+$/;
/** t('key' ... — хвост через lookahead: он нужен только чтобы разглядеть
 *  запасное значение, и НЕ должен съедаться, иначе соседний вызов t() в
 *  тех же 200 символах выпал бы из проверки. Хвост многострочный
 *  намеренно: длинный запасной текст часто переносят на следующую строку. */
const T_CALL = /\bt\(\s*(['"])([^'"\n]+)\1(?=([\s\S]{0,200}))/g;
/** <Trans i18nKey="key"> */
const TRANS = /i18nKey\s*=\s*(['"])([^'"\n]+)\1/g;

/**
 * Второй аргумент-строка или `defaultValue` в опциях — это запасной текст.
 * i18next покажет его вместо ключа, значит отсутствие ключа не аварийно
 * (так намеренно сделано там, где значение приходит с бэкенда и словарь
 * заведомо может его не знать — см. `HRTasks`, `KanbanBoard`).
 */
function hasInlineDefault(tail: string): boolean {
  // Строкой вторым аргументом; перенос строки допустим — его покрывает \s.
  if (/^\s*,\s*['"`]/.test(tail)) return true;
  // Либо `defaultValue` в объекте опций. Запятая перед ним обязательна,
  // иначе сюда попало бы слово из соседнего, ничем не связанного кода.
  return /^\s*,[\s\S]{0,200}?\bdefaultValue\b/.test(tail);
}

function collectUsedKeys(): Array<{ key: string; where: string }> {
  const used: Array<{ key: string; where: string }> = [];
  for (const file of sourceFiles(SRC)) {
    const text = fs.readFileSync(file, 'utf-8');
    const rel = path.relative(FRONTEND, file).split(path.sep).join('/');
    const lineOf = (idx: number) => text.slice(0, idx).split('\n').length;

    for (const m of text.matchAll(T_CALL)) {
      const [, , key, tail] = m;
      if (!KEYISH.test(key) || hasInlineDefault(tail)) continue;
      used.push({ key, where: rel + ':' + lineOf(m.index ?? 0) });
    }
    for (const m of text.matchAll(TRANS)) {
      const key = m[2];
      if (!KEYISH.test(key)) continue;
      used.push({ key, where: rel + ':' + lineOf(m.index ?? 0) });
    }
  }
  return used;
}

/** Русский требует множественных форм: i18next ищет `key_one`/`_few`/`_many`. */
function present(key: string, dict: Set<string>): boolean {
  if (dict.has(key)) return true;
  return ['_one', '_few', '_many', '_other', '_zero'].some((s) => dict.has(key + s));
}

describe('i18n: ключи из кода существуют в словаре', () => {
  const ru = loadLocale('ru');
  const en = loadLocale('en');
  const used = collectUsedKeys();

  it('находит ключи в исходниках (сама проверка не выродилась в пустую)', () => {
    expect(used.length).toBeGreaterThan(100);
  });

  it('каждый ключ без запасного текста есть в ru — иначе на экране будет сам ключ', () => {
    const missing = used
      .filter(({ key }) => !present(key, ru))
      .map(({ key, where }) => `${where}  ${key}`);
    expect(missing.sort()).toEqual([]);
  });

  it('те же ключи есть в en — иначе в англ. интерфейсе всплывёт русский текст', () => {
    const missing = used
      .filter(({ key }) => present(key, ru) && !present(key, en))
      .map(({ key, where }) => `${where}  ${key}`);
    expect([...new Set(missing)].sort()).toEqual([]);
  });
});
