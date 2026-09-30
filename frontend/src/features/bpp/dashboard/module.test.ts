/**
 * Пункт меню «Дашборд оплат» — узел `bpp.dashboard` `view` (ФД, ТД, ОД,
 * ГД, БУХ); без права или без `bpp:read` пункта нет. В меню — сразу после
 * «Оплаты факт».
 */
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

describe('«Дашборд оплат»', () => {
  it('пункт меню ведёт в dashboard', () => {
    expect(bppModule.menu?.labelFallback).toBe('Дашборд оплат');
    expect(bppModule.menu?.path).toBe('dashboard');
    expect(bppModule.routes.map((route) => route.path)).toEqual(['dashboard']);
  });

  it('виден по bpp.dashboard view, иначе скрыт', () => {
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.dashboard': ['view'] }))).toBe(true);
    expect(moduleVisible(bppModule, withRights(true, { 'bpp.bank': ['view', 'edit'] }))).toBe(false);
    expect(moduleVisible(bppModule, withRights(false, { 'bpp.dashboard': ['view'] }))).toBe(false);
  });

  it('в меню — сразу после «Оплаты факт»', () => {
    const withMenu = bppModules.filter((module) => module.menu).map((module) => module.key);
    expect(withMenu.indexOf('dashboard')).toBe(withMenu.indexOf('bank') + 1);
  });
});
