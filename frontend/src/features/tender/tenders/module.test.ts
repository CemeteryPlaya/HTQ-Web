/**
 * Подразделы «Тендеры» и «Потенциальные поставщики» (T2.3): пункты меню,
 * маршруты и видимость по узлам `tender.tenders` и `tender.prospects`.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';

import { tenderModules, tenderModuleVisible } from '../modules';
import { tenderModule as prospectsModule } from '../prospects/module';
import { tenderModule as tendersModule } from './module';

const rights = (level: boolean, nodes: Record<string, string[]>) => ({
  atLeast: (module: string) => level && module === 'tender',
  can: (node: string, flag: string) => (nodes[node] ?? []).includes(flag),
}) as unknown as Permissions;

describe('«Тендеры»', () => {
  it('пункт меню и маршруты реестра и карточки', () => {
    expect(tendersModule.menu).toMatchObject({ path: 'tenders', labelFallback: 'Тендеры' });
    expect(tendersModule.routes.map((route) => route.path)).toEqual(['tenders', 'tenders/:id']);
  });

  it('виден при tender:read и tender.tenders view', () => {
    expect(tenderModuleVisible(tendersModule, rights(true, { 'tender.tenders': ['view'] }))).toBe(true);
    expect(tenderModuleVisible(tendersModule, rights(true, {}))).toBe(false);
    expect(tenderModuleVisible(tendersModule, rights(false, { 'tender.tenders': ['view'] }))).toBe(false);
  });
});

describe('«Потенциальные поставщики»', () => {
  it('пункт меню и маршрут справочника', () => {
    expect(prospectsModule.menu).toMatchObject({ path: 'prospects', labelFallback: 'Потенциальные поставщики' });
    expect(prospectsModule.routes.map((route) => route.path)).toEqual(['prospects']);
  });

  it('виден при tender:read и tender.prospects view', () => {
    expect(tenderModuleVisible(prospectsModule, rights(true, { 'tender.prospects': ['view'] }))).toBe(true);
    expect(tenderModuleVisible(prospectsModule, rights(true, { 'tender.tenders': ['view'] }))).toBe(false);
  });
});

describe('порядок меню раздела', () => {
  it('обзор → заявки → тендеры → поставщики', () => {
    const menu = tenderModules.filter((module) => module.menu).map((module) => module.key);
    expect(menu).toEqual(['overview', 'requests', 'tenders', 'prospects']);
  });
});
