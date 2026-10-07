/**
 * Подраздел «Заявки» раздела «Тендеры» (T1.4): пункт меню и маршруты
 * реестра, формы и карточки; виден при `tender:read` и `view` на узле
 * `tender.requests`.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';

import { tenderModules, tenderModuleVisible } from '../modules';
import { tenderModule } from './module';

const rights = (level: boolean, nodes: Record<string, string[]>) => ({
  atLeast: (module: string) => level && module === 'tender',
  can: (node: string, flag: string) => (nodes[node] ?? []).includes(flag),
}) as unknown as Permissions;

describe('«Заявки» тендерного модуля', () => {
  it('пункт меню и маршруты реестра, формы и карточки', () => {
    expect(tenderModule.menu).toMatchObject({ path: 'requests', labelFallback: 'Заявки на тендер' });
    expect(tenderModule.routes.map((route) => route.path)).toEqual([
      'requests', 'requests/new', 'requests/:id', 'requests/:id/edit',
    ]);
    expect(tenderModules.map((module) => module.key)).toContain('requests');
  });

  it('виден при tender:read и tender.requests view, иначе скрыт', () => {
    expect(tenderModuleVisible(tenderModule, rights(true, { 'tender.requests': ['view'] }))).toBe(true);
    expect(tenderModuleVisible(tenderModule, rights(true, {}))).toBe(false);
    expect(tenderModuleVisible(tenderModule, rights(false, { 'tender.requests': ['view'] }))).toBe(false);
  });

  it('после «Обзора» в меню', () => {
    const menu = tenderModules.filter((module) => module.menu).map((module) => module.key);
    expect(menu.indexOf('overview')).toBe(0);
    expect(menu.indexOf('requests')).toBeGreaterThan(0);
  });
});
