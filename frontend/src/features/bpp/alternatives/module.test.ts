/** Пункт «Альтернативы» — узел `bpp.alternatives` view; в меню между «Счетами» и «Оплатами факт». */
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

describe('«Альтернативы»', () => {
  it('маршруты — лента и карточка АП (цель ссылок KPI и уведомлений)', () => {
    expect(bppModule.menu?.labelFallback).toBe('Альтернативы');
    expect(bppModule.order).toBe(65);
    expect(bppModule.routes.map((route) => route.path)).toEqual(['alternatives', 'alternatives/:id']);
  });

  it('скрыт без права bpp.alternatives view', () => {
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.alternatives': ['view'] }))).toBe(true);
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.kpi': ['view'] }))).toBe(false);
    expect(moduleVisible(bppModule, withRights(false, { 'bpp.alternatives': ['view'] }))).toBe(false);
  });

  it('в меню — после «Счетов на оплату», до «Оплат факт»', () => {
    const keys = bppModules.filter((module) => module.menu).map((module) => module.key);
    expect(keys.indexOf('alternatives')).toBe(keys.indexOf('invoices') + 1);
  });
});
