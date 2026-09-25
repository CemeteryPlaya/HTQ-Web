/**
 * `useHRLevel` после задачи 10 блока I — тонкая обёртка над `usePermissions`
 * ради четырёх экранов `src/pages/contracts/*` (см. докстринг хука): из него
 * остались `hasPerm`, `isLoading`, `isError`, `permissions`. Здесь
 * проверяется ровно то, что осталось: `hasPerm` раскрывает старый ключ в
 * узел реестра и ВСЕ его признаки (`backend/apps/hr/legacy_roles.py::
 * KEY_TO_NODE`), а не выводит ответ из агрегированного уровня модуля;
 * ключ чужой аппки — `false`; «не загрузилось» отличимо от «прав нет».
 * Уровни и `can*`-предикаты сняты вместе с потребителями — тестов на них
 * больше нет намеренно.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ACCESS_TOKEN_KEY } from '@/lib/auth/profileStorage';
import type { AccessMe } from '@/types/access';

import { useHRLevel } from './useHRLevel';

const getMe = vi.fn<() => Promise<AccessMe>>();

vi.mock('@/api/access', () => ({
  accessApi: { getMe: () => getMe() },
  default: { getMe: () => getMe() },
}));

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

const baseMe = (overrides: Partial<AccessMe>): AccessMe => ({
  company: 'hi-tech-qazaqstan',
  permissions: {},
  depth: {},
  hidden_pages: [],
  subordinate_companies: [],
  inherited_from: [],
  ...overrides,
});

beforeEach(() => {
  getMe.mockReset();
  // usePermissions без токена права не спрашивает вовсе (аноним на лендинге),
  // поэтому тестам вошедшего нужен токен — как в usePermissions.test.tsx.
  window.localStorage.setItem(ACCESS_TOKEN_KEY, 'access-token');
});

afterEach(() => {
  window.localStorage.clear();
});

describe('useHRLevel (только hasPerm для contracts)', () => {
  it('отдаёт ровно hasPerm, permissions, isLoading, isError — ничего из снятого', async () => {
    getMe.mockResolvedValue(baseMe({}));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(Object.keys(result.current).sort()).toEqual(['hasPerm', 'isError', 'isLoading', 'permissions']);
    expect(result.current.permissions).toEqual([]);
  });

  it('hasPerm считает по узлу и всем его признакам, а не по уровню модуля', async () => {
    // Уровень модуля 'hr' здесь — 'admin' (delete есть в поддереве, но на
    // hr.documents), а у hr.employees в карте глубины только 'view'. Ключи
    // на hr.employees с create/edit/delete обязаны быть false: вывод из
    // уровня («admin → всё можно») соврал бы, что сотрудника можно удалить.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
      depth: {
        'hr.employees': ['view'],
        'hr.documents': ['view', 'create', 'edit', 'delete'],
      },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasPerm('hr.employees.view')).toBe(true);
    expect(result.current.hasPerm('hr.employees.edit')).toBe(false);
    expect(result.current.hasPerm('hr.employees.create')).toBe(false);
    expect(result.current.hasPerm('hr.employees.delete')).toBe(false);
    expect(result.current.hasPerm('hr.documents.manage')).toBe(true);
  });

  it('перевод считается по своему узлу hr.employees.transfer, а не по hr.employees', async () => {
    // Фикс-раунд 1 задачи 9 блока I: у перевода отдельный под-узел (сервер —
    // access/migrations/0008, hr-middle несёт на нём явный запрет). С правом
    // править карточку, но запретом на перевод, ключ перевода обязан быть
    // false — иначе интерфейс покажет то, на что сервер ответит 403.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'write', scope: { kind: 'department', id: 5 } } },
      depth: {
        'hr.employees': ['view', 'edit'],
        'hr.employees.transfer': [],
      },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasPerm('hr.employees.edit')).toBe(true);
    expect(result.current.hasPerm('hr.employees.transfer')).toBe(false);

    // И наоборот: узел выдан явно (senior/lead) — перевод есть.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'write', scope: { kind: 'company', id: null } } },
      depth: {
        'hr.employees': ['view', 'create', 'edit'],
        'hr.employees.transfer': ['view', 'edit'],
      },
    }));
    const senior = renderHook(() => useHRLevel(), { wrapper });
    await waitFor(() => expect(senior.result.current.isLoading).toBe(false));
    expect(senior.result.current.hasPerm('hr.employees.transfer')).toBe(true);
  });

  it('hasPerm переводит старый ключ прав в узел+признаки, а не строку из ответа', async () => {
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'read', scope: { kind: 'company', id: null } } },
      depth: { 'hr.production_calendar': ['view'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    // Узел несёт только 'view' — 'manage' (полный CRUD) требует больше.
    expect(result.current.hasPerm('hr.calendar.view')).toBe(true);
    expect(result.current.hasPerm('hr.calendar.manage')).toBe(false);
  });

  it('hasPerm отдаёт false для ключа, узел которого не принадлежит hr', async () => {
    // contracts.advance_payment.record_payment сознательно не переведён —
    // тот же повод, по которому backend (apps/hr/legacy_roles.py::
    // DEFERRED_KEYS) не мапит его сам: узел этой области владеет
    // apps.contracts, а не apps.hr. Даже при максимальной глубине на hr этот
    // ключ обязан остаться false, а не превратиться в «пусти всех» по
    // ошибке маппинга. Ровно этот вызов делают экраны contracts.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
      depth: { hr: ['view', 'create', 'edit', 'delete'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasPerm('contracts.advance_payment.record_payment')).toBe(false);
    expect(result.current.hasPerm('contracts.accountable_funds_request.mark_paid')).toBe(false);
    expect(result.current.hasPerm('contracts.contract_payment.record_payment')).toBe(false);
  });

  it('различает «права не загрузились» и «прав нет»', async () => {
    // Оба случая отдают hasPerm → false — так и должно быть, отказ в закрытую
    // (докстринг usePermissions). Но это РАЗНЫЕ ситуации: одна — временная
    // сетевая проблема, другая — штатное «доступа нет». `isError` — это и
    // есть отличие.
    getMe.mockRejectedValue(new Error('сеть недоступна'));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasPerm('hr.employees.view')).toBe(false);
    expect(result.current.isError).toBe(true);
  });
});
