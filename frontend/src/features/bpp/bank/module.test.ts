/**
 * Пункты меню «Оплаты факт» и «Настройки» по правам (план этапа 3 A,
 * задача 5): «Оплаты факт» — узел `bpp.bank` `view` (ФД, БУХ),
 * «Настройки» — `bpp.settings` `view` (ФД, АДМ); без `bpp:read` — ни одного.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';

import { moduleVisible } from '../core/moduleAccess';
import { bppModules } from '../modules';
import { bppModule as settingsModule } from '../settings/module';
import { bppModule as bankModule } from './module';

const withRights = (bpp: boolean, nodes: Record<string, DepthFlag[]>) => ({
  atLeast: (module: string) => bpp && module === 'bpp',
  can: (node: string, flag: DepthFlag) => (nodes[node] ?? []).includes(flag),
}) as unknown as Permissions;

describe('«Оплаты факт»', () => {
  it('пункт меню ведёт в bank, маршруты — реестр, форма, загрузка', () => {
    expect(bankModule.menu?.labelFallback).toBe('Оплаты факт');
    expect(bankModule.menu?.path).toBe('bank');
    expect(bankModule.routes.map((route) => route.path)).toEqual(['bank', 'bank/new', 'bank/:id']);
  });

  it('виден по bpp.bank view: ФД и БУХ — да, АДМ без узла — нет', () => {
    expect(moduleVisible(bankModule, withRights(true, { 'bpp.bank': ['view', 'edit'] }))).toBe(true);
    expect(moduleVisible(bankModule, withRights(true, { 'bpp.bank': ['view'] }))).toBe(true);
    expect(moduleVisible(bankModule, withRights(true, { 'bpp.settings': ['view', 'edit'] }))).toBe(false);
    expect(moduleVisible(bankModule, withRights(false, { 'bpp.bank': ['view'] }))).toBe(false);
  });
});

describe('«Настройки»', () => {
  it('пункт меню ведёт в settings', () => {
    expect(settingsModule.menu?.labelFallback).toBe('Настройки');
    expect(settingsModule.routes.map((route) => route.path)).toEqual(['settings']);
  });

  it('виден по bpp.settings view: АДМ — да, БУХ (только bpp.bank) — нет', () => {
    expect(moduleVisible(settingsModule, withRights(true, { 'bpp.settings': ['view', 'edit'] }))).toBe(true);
    expect(moduleVisible(settingsModule, withRights(true, { 'bpp.bank': ['view'] }))).toBe(false);
    expect(moduleVisible(settingsModule, withRights(false, { 'bpp.settings': ['view'] }))).toBe(false);
  });

  it('оба подмодуля подключены автодискавери раздела, «Оплаты факт» — раньше «Настроек»', () => {
    const keys = bppModules.map((module) => module.key);
    expect(keys.filter((key) => key === 'bank')).toHaveLength(1);
    expect(keys.filter((key) => key === 'settings')).toHaveLength(1);
    expect(keys.indexOf('bank')).toBeLessThan(keys.indexOf('settings'));
  });
});
