import { describe, expect, it } from 'vitest';

import { LEVEL_ORDER, levelFor, meetsLevel, scopeFor } from './permissions';
import type { PermissionMap } from './permissions';

const map: PermissionMap = {
  hr: { level: 'admin', scope: { kind: 'company', id: null } },
  tasks: { level: 'write', scope: { kind: 'department', id: 3 } },
};

describe('meetsLevel', () => {
  it('пускает, когда фактический уровень выше требуемого', () => {
    expect(meetsLevel('write', 'read')).toBe(true);
  });

  it('пускает при равенстве — правило «не ниже», а не «строго выше»', () => {
    expect(meetsLevel('read', 'read')).toBe(true);
  });

  it('отвергает, когда фактический уровень ниже требуемого', () => {
    expect(meetsLevel('read', 'write')).toBe(false);
  });

  it('никого не пускает с уровнем none, кроме требования none', () => {
    expect(meetsLevel('none', 'read')).toBe(false);
    expect(meetsLevel('none', 'none')).toBe(true);
  });
});

describe('LEVEL_ORDER', () => {
  // Сторож на несущую константу: сравнение уровней — это индекс в этом
  // массиве, поэтому его перестановка молча вывернула бы доступ наизнанку.
  it('перечисляет уровни строго по возрастанию', () => {
    expect([...LEVEL_ORDER]).toEqual(['none', 'read', 'write', 'admin']);
  });
});

describe('levelFor', () => {
  it('считает отсутствующий в карте модуль уровнем none', () => {
    expect(levelFor({}, 'hr')).toBe('none');
  });

  it('возвращает уровень присутствующего модуля', () => {
    expect(levelFor(map, 'tasks')).toBe('write');
  });
});

describe('scopeFor', () => {
  it('возвращает область присутствующего модуля', () => {
    expect(scopeFor(map, 'tasks')).toEqual({ kind: 'department', id: 3 });
  });

  it('возвращает null для модуля, которого нет в карте', () => {
    // Область без доступа не имеет смысла, и подставлять «компанию»
    // было бы опаснее всего: это самая широкая из областей.
    expect(scopeFor(map, 'contracts')).toBeNull();
  });
});
