/**
 * Сторож на мёртвый ролевой словарь (§6 B3 спеки стадии 2).
 *
 * Бэкенд выдаёт ровно три роли — `admin`, `staff`, `user`
 * (`apps/users/services/profile_service.py::roles_for`). Всё остальное, что
 * когда-либо перечислялось во фронте — `hr_manager`, `senior_hr`, `junior_hr`,
 * `senior_manager`, `junior_manager`, `editors`, `superuser`, — не приезжало
 * никогда, то есть ветки на этих строках были недостижимы.
 *
 * Опасность таких строк в том, что код с ними **выглядит работающим**: гейт
 * есть, список ролей внушительный, проверка написана. Именно отсутствие этой
 * проверки позволило словарю дожить до второй стадии. Поэтому сторож
 * запрещает не «неправильные» строки, а строки, которых просто не бывает.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/** Роли, которых бэкенд не выдаёт никогда. */
const DEAD_ROLES = [
  'hr_manager',
  'senior_hr',
  'junior_hr',
  'senior_manager',
  'junior_manager',
  'editors',
  'superuser',
];

/** Символы снятого словаря — их не должно остаться и в импортах. */
const DEAD_SYMBOLS = [
  'ELEVATED_ROLES',
  'HR_ROLES',
  'EDITOR_ROLES',
  'EMPLOYEE_ROLES',
];

const SRC = join(__dirname, '..', '..');

const walk = (dir: string, out: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // locales — тексты интерфейса, не код; тесты сами перечисляют мёртвые
      // строки, когда проверяют, что их нет.
      if (entry === 'locales' || entry === 'node_modules') continue;
      walk(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
};

const rel = (file: string) => file.slice(SRC.length + 1).replace(/\\/g, '/');

/**
 * Ловим только строковые литералы в кавычках.
 *
 * Иначе сторож ругается на настоящее поле пользователя `is_superuser` (оно
 * живое: бэкенд его отдаёт и админка им управляет) и на упоминания мёртвых
 * ролей в комментариях, объясняющих, почему их быть не должно. Обе эти вещи
 * запрещать нельзя — запретив, мы заставили бы обходить сторожа, а не
 * чинить код.
 */
const deadRoleOffenders = () => {
  const found: string[] = [];
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf8');
    for (const role of DEAD_ROLES) {
      if (new RegExp(`['"]${role}['"]`).test(text)) {
        found.push(`${rel(file)} → '${role}'`);
      }
    }
  }
  return found;
};

const deadSymbolOffenders = () => {
  const found: string[] = [];
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf8');
    for (const symbol of DEAD_SYMBOLS) {
      // Слово целиком: STAFF_OR_ADMIN_ROLES не должен считаться за ADMIN_ROLES.
      if (new RegExp(`\\b${symbol}\\b`).test(text)) {
        found.push(`${rel(file)} → ${symbol}`);
      }
    }
  }
  return found;
};

describe('мёртвый ролевой словарь', () => {
  it('нигде не сравнивается с ролями, которых бэкенд не выдаёт', () => {
    expect(deadRoleOffenders()).toEqual([]);
  });

  it('не оставил после себя снятых констант', () => {
    expect(deadSymbolOffenders()).toEqual([]);
  });
});
