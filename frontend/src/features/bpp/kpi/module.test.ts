/** Пункт «Отчёты» — узел `bpp.kpi` view; в меню сразу после «Дашборда оплат». */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';

import { moduleVisible } from '../core/moduleAccess';
import { bppModules } from '../modules';
import { bppModule } from './module';

const withRights = (bpp: boolean, nodes: Record<string, DepthFlag[]>) => ({
  atLeast: (module: string) => bpp && module === 'bpp',
  can: (node: string, flag: DepthFlag) => (nodes[node] ?? []).includes(flag),
}) as unknown as Permissions;

describe('«Отчёты»', () => {
  it('маршруты — отчёт и карточка записи', () => {
    expect(bppModule.menu?.labelFallback).toBe('Отчёты');
    expect(bppModule.routes.map((route) => route.path)).toEqual(['kpi', 'kpi/:id']);
  });

  it('виден по bpp.kpi view, иначе скрыт', () => {
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.kpi': ['view'] }))).toBe(true);
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.bank': ['view'] }))).toBe(false);
    expect(moduleVisible(bppModule, withRights(false, { 'bpp.kpi': ['view'] }))).toBe(false);
  });

  it('в меню — сразу после «Дашборда оплат»', () => {
    const keys = bppModules.filter((module) => module.menu).map((module) => module.key);
    expect(keys.indexOf('kpi')).toBe(keys.indexOf('dashboard') + 1);
  });
});
