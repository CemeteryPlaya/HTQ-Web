/**
 * Пункт меню «Обзор» — при `bpp:read`, первым в меню: корень раздела
 * (`/bpp`) ведёт на первый видимый пункт, то есть сюда.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';

import { moduleVisible } from '../core/moduleAccess';
import { bppModules } from '../modules';
import { bppModule } from './module';

const withBpp = (bpp: boolean) => ({
  atLeast: (module: string) => bpp && module === 'bpp',
  can: () => false,
}) as unknown as Permissions;

describe('«Обзор»', () => {
  it('пункт меню ведёт в overview', () => {
    expect(bppModule.menu?.labelFallback).toBe('Обзор');
    expect(bppModule.menu?.path).toBe('overview');
    expect(bppModule.routes.map((route) => route.path)).toEqual(['overview']);
  });

  it('виден при bpp:read без прав узлов, без bpp:read — скрыт', () => {
    expect(moduleVisible(bppModule, withBpp(true))).toBe(true);
    expect(moduleVisible(bppModule, withBpp(false))).toBe(false);
  });

  it('первый пункт меню раздела', () => {
    expect(bppModules.find((module) => module.menu)?.key).toBe('overview');
  });
});
