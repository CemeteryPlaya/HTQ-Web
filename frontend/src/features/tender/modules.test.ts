/**
 * Автодискавери подразделов тендерного модуля (T0.4, мастер-план §3.1 —
 * по образцу `features/bpp/modules.ts`): `collectModules` сортирует
 * манифесты по `order`/`key` и падает на подразделе без `tenderModule`,
 * вместо того чтобы молча его пропустить.
 */
import { describe, expect, it } from 'vitest';

import {
  TENDER_BASE,
  collectModules,
  tenderMenuHref,
  tenderModules,
  type TenderModule,
  type TenderModuleExports,
} from './modules';

const moduleOf = (key: string, order: number): TenderModule => ({ key, order, routes: [] });

describe('collectModules', () => {
  it('сортирует по order', () => {
    const loaded: Record<string, TenderModuleExports> = {
      './b/module.tsx': { tenderModule: moduleOf('b', 20) },
      './a/module.tsx': { tenderModule: moduleOf('a', 10) },
    };
    expect(collectModules(loaded).map((m) => m.key)).toEqual(['a', 'b']);
  });

  it('при равном order сортирует по key', () => {
    const loaded: Record<string, TenderModuleExports> = {
      './z/module.tsx': { tenderModule: moduleOf('z', 1) },
      './a/module.tsx': { tenderModule: moduleOf('a', 1) },
    };
    expect(collectModules(loaded).map((m) => m.key)).toEqual(['a', 'z']);
  });

  it('падает на подразделе без tenderModule, называя его путь', () => {
    const loaded: Record<string, TenderModuleExports> = { './broken/module.tsx': {} };
    expect(() => collectModules(loaded)).toThrow(/broken\/module\.tsx/);
  });

  it('пустой набор подразделов — пустой список, а не ошибка', () => {
    expect(collectModules({})).toEqual([]);
  });
});

describe('tenderMenuHref', () => {
  it('строит адрес внутри раздела /tender', () => {
    expect(TENDER_BASE).toBe('/tender');
    expect(tenderMenuHref('overview')).toBe('/tender/overview');
    expect(tenderMenuHref('/requests')).toBe('/tender/requests');
  });
});

describe('tenderModules', () => {
  it('ключи уникальны, порядок по order', () => {
    const keys = tenderModules.map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
    const orders = tenderModules.map((m) => m.order);
    expect(orders).toEqual([...orders].sort((a, b) => a - b));
  });

  it('первый пункт меню — «Обзор» (на него ведёт корень раздела)', () => {
    const first = tenderModules.find((m) => m.menu);
    expect(first?.key).toBe('overview');
    expect(first?.menu?.path).toBe('overview');
    expect(first?.menu?.labelFallback).toBe('Обзор');
    expect(first?.routes.map((r) => r.path)).toEqual(['overview']);
  });
});
