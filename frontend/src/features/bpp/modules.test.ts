/**
 * Автодискавери подмодулей раздела «Закупки и оплаты» (план этапа 2 A,
 * задача 2): `collectModules` сортирует манифесты по `order`/`key` и падает
 * на подмодуле без `bppModule`, вместо того чтобы молча его пропустить.
 */
import { describe, expect, it } from 'vitest';

import { bppModules, collectModules, type BppModule, type BppModuleExports } from './modules';

const moduleOf = (key: string, order: number): BppModule => ({ key, order, routes: [] });

describe('collectModules', () => {
  it('сортирует по order', () => {
    const loaded: Record<string, BppModuleExports> = {
      './b/module.tsx': { bppModule: moduleOf('b', 20) },
      './a/module.tsx': { bppModule: moduleOf('a', 10) },
    };
    expect(collectModules(loaded).map((m) => m.key)).toEqual(['a', 'b']);
  });

  it('при равном order сортирует по key', () => {
    const loaded: Record<string, BppModuleExports> = {
      './z/module.tsx': { bppModule: moduleOf('z', 1) },
      './a/module.tsx': { bppModule: moduleOf('a', 1) },
    };
    expect(collectModules(loaded).map((m) => m.key)).toEqual(['a', 'z']);
  });

  it('падает на подмодуле без bppModule, называя его путь', () => {
    const loaded: Record<string, BppModuleExports> = {
      './broken/module.tsx': {},
    };
    expect(() => collectModules(loaded)).toThrow(/broken\/module\.tsx/);
  });

  it('пустой набор подмодулей — пустой список, а не ошибка', () => {
    expect(collectModules({})).toEqual([]);
  });
});

describe('bppModules', () => {
  it('модули пакета собраны: ключи уникальны, порядок по order', () => {
    const keys = bppModules.map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
    const orders = bppModules.map((m) => m.order);
    expect(orders).toEqual([...orders].sort((a, b) => a - b));
  });
});
