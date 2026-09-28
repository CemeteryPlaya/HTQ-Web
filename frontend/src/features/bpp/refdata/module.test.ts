/**
 * Манифест подмодуля «Справочники» (задача 9, A2.4): пункт 9 меню ТЗ §05,
 * виден по `refdata:read` — у справочников свой модуль прав.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';

import { moduleVisible } from '../core/moduleAccess';
import { bppModules } from '../modules';
import { bppModule } from './module';

const withLevel = (levels: Record<string, 'none' | 'read' | 'write' | 'admin'>) => {
  const rank = { none: 0, read: 1, write: 2, admin: 3 };
  return {
    atLeast: (module: string, required: keyof typeof rank) =>
      rank[levels[module] ?? 'none'] >= rank[required],
  } as unknown as Permissions;
};

describe('refdata bppModule', () => {
  it('пункт меню «Справочники» ведёт на refdata', () => {
    expect(bppModule.key).toBe('refdata');
    expect(bppModule.menu?.labelFallback).toBe('Справочники');
    expect(bppModule.menu?.path).toBe('refdata');
    expect(bppModule.routes.map((r) => r.path)).toEqual(['refdata']);
  });

  it('виден по refdata:read, а не по bpp', () => {
    expect(moduleVisible(bppModule, withLevel({ refdata: 'read' }))).toBe(true);
    expect(moduleVisible(bppModule, withLevel({ bpp: 'admin' }))).toBe(false);
  });

  it('подключён автодискавери раздела', () => {
    expect(bppModules.filter((m) => m.key === 'refdata')).toHaveLength(1);
  });
});
