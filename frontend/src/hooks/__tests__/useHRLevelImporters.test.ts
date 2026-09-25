/**
 * Сторож задачи 10 блока I «Единая модель прав».
 *
 * `useHRLevel` оставлен ТОЛЬКО ради четырёх экранов `src/pages/contracts/*`
 * (зона другого разработчика, roadmap §6) — все остальные потребители
 * переведены на `usePermissions` напрямую. Новый импорт хука где-либо ещё —
 * возврат ко второй, параллельной модели прав, и ловится он здесь
 * статически, по исходникам (тот же приём, что у
 * `lib/ux/__tests__/uxContract.test.ts` и `lib/i18n/__tests__/
 * translationKeys.test.ts`): ни typecheck, ни линт не отличат «читает права
 * из единого источника» от «читает из обёртки над ним».
 *
 * Считается импортом и мок в тесте (`vi.mock('@/hooks/useHRLevel', …)`):
 * мок появляется только у файла, который хук реально зовёт.
 *
 * Когда экраны contracts перейдут на `usePermissions`, список ниже
 * опустеет — и тогда хук вместе с этим сторожем удаляется (см. докстринг
 * `useHRLevel.ts`).
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, '../..');

/** Единственный каталог, откуда импорт хука допустим. */
const ALLOWED_PREFIX = 'pages/contracts/';

/** Сам хук, его тест и этот сторож (в нём образцы импорта) — не потребители. */
const SELF = new Set([
  'hooks/useHRLevel.ts',
  'hooks/useHRLevel.test.tsx',
  'hooks/__tests__/useHRLevelImporters.test.ts',
]);

/**
 * Импорт по алиасу или относительный — статический (`from`), динамический
 * (`import(`), плюс моки в тестах (`vi.mock(`, `vi.doMock(`). Динамическая
 * форма добавлена фикс-раундом 1: `await import('@/hooks/useHRLevel')`
 * обходил бы сторож молча.
 */
const IMPORT_RE = /(?:from\s*|import\(\s*|vi\.(?:do)?[mM]ock\(\s*)['"](?:@\/hooks\/useHRLevel|\.{1,2}\/(?:hooks\/)?useHRLevel)['"]/;

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules') sourceFiles(full, acc);
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      acc.push(full);
    }
  }
  return acc;
}

const rel = (file: string) => path.relative(SRC, file).split(path.sep).join('/');

describe('useHRLevel — импортёры', () => {
  it('хук импортируют только src/pages/contracts/*', () => {
    const importers = sourceFiles(SRC)
      .map(rel)
      .filter((file) => !SELF.has(file))
      .filter((file) => IMPORT_RE.test(fs.readFileSync(path.join(SRC, file), 'utf-8')));

    const violations = importers.filter((file) => !file.startsWith(ALLOWED_PREFIX));

    expect(
      violations,
      `useHRLevel оставлен только для ${ALLOWED_PREFIX}; права читаются из usePermissions ` +
        `(can(node, flag) / atLeast / scope). Нарушители:\n  ${violations.join('\n  ')}`,
    ).toEqual([]);
  });

  it('регулярка ловит алиас, относительный путь, динамический импорт и оба мока', () => {
    expect(IMPORT_RE.test("import { useHRLevel } from '@/hooks/useHRLevel';")).toBe(true);
    expect(IMPORT_RE.test("import { useHRLevel } from './useHRLevel';")).toBe(true);
    expect(IMPORT_RE.test("import { useHRLevel } from '../hooks/useHRLevel';")).toBe(true);
    expect(IMPORT_RE.test("const m = await import('@/hooks/useHRLevel');")).toBe(true);
    expect(IMPORT_RE.test("import( \"../hooks/useHRLevel\" )")).toBe(true);
    expect(IMPORT_RE.test("vi.mock('@/hooks/useHRLevel', () => ({}))")).toBe(true);
    expect(IMPORT_RE.test("vi.doMock('@/hooks/useHRLevel', () => ({}))")).toBe(true);
    // Упоминание в комментарии — не импорт.
    expect(IMPORT_RE.test('// раньше читалось из useHRLevel')).toBe(false);
  });
});
