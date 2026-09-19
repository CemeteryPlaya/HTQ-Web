/**
 * Задача 8 блока I: `useHRLevel` больше не ходит в `hr/v1/employees/hr-level/`
 * — уровень и предикаты считаются из прав (`usePermissions`, `/access/v1/me`).
 * Публичный интерфейс хука не меняется, поэтому здесь проверяется именно
 * СЧЁТ, а не форма ответа: соответствие уровней взято дословно из
 * `backend/apps/access/depth.py::legacy_level` (delete → admin, create|edit →
 * write, view → read), а `can_*`-предикаты обязаны читаться по узлам
 * реестра (`can(node, flag)`), а не выводиться из агрегированного уровня —
 * иначе право на один узел кадрового поддерева протекало бы на все остальные.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
});

describe('useHRLevel', () => {
  it('admin на hr отдаёт lead', async () => {
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
      depth: { hr: ['view', 'create', 'edit', 'delete'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBe('lead');
    expect(result.current.isLead).toBe(true);
    expect(result.current.hasHrAccess).toBe(true);
  });

  it('write на hr с областью «отдел» отдаёт middle', async () => {
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'write', scope: { kind: 'department', id: 7 } } },
      depth: { hr: ['view', 'create', 'edit'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBe('middle');
    expect(result.current.isMiddle).toBe(true);
    expect(result.current.scopeDepartmentId).toBe(7);
  });

  it('write на hr с областью «вся компания» отдаёт senior', async () => {
    // Не из обязательного списка брифа, но без этого случая `isSenior`
    // (которым гейтятся ~9 экранов HR) никогда не стал бы true иначе как
    // через lead — старый уровень 'senior' был бы недостижим. Разница
    // middle/senior — это ОБЛАСТЬ выдачи роли (department/company), а не
    // признак глубины (см. решение 1, backend/apps/hr/legacy_roles.py,
    // комментарий у EMPLOYEES_VIEW_ALL) — тот же расчёт, что и на бэкенде
    // в `apps/access/services/resolve.py::permissions_for`.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'write', scope: { kind: 'company', id: null } } },
      depth: { hr: ['view', 'create', 'edit'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBe('senior');
    expect(result.current.isSenior).toBe(true);
    expect(result.current.scopeDepartmentId).toBeNull();
  });

  it('read на hr отдаёт junior', async () => {
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'read', scope: { kind: 'department', id: 4 } } },
      depth: { hr: ['view'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBe('junior');
    expect(result.current.isJunior).toBe(true);
    expect(result.current.scopeDepartmentId).toBe(4);
  });

  it('без прав на hr отдаёт null', async () => {
    getMe.mockResolvedValue(baseMe({}));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBeNull();
    expect(result.current.hasHrAccess).toBe(false);
    expect(result.current.isError).toBe(false);
  });

  it('can_*-предикаты считаются по узлу, а не по агрегированному уровню', async () => {
    // Уровень модуля 'hr' здесь — 'admin' (delete есть в поддереве, только
    // не на hr.employees, а на hr.documents), поэтому `level` обязан
    // остаться 'lead'. Но `canDeleteEmployee`/`canWriteBasic`/
    // `canCreateEmployee` обязаны быть false: у hr.employees в карте
    // глубины есть только 'view'. Если бы предикаты выводились из уровня
    // ('lead' → всё можно), этот тест бы упал.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
      depth: {
        'hr.employees': ['view'],
        'hr.documents': ['view', 'create', 'edit', 'delete'],
      },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBe('lead');
    expect(result.current.canReadAll).toBe(true);
    expect(result.current.canWriteBasic).toBe(false);
    expect(result.current.canCreateEmployee).toBe(false);
    expect(result.current.canDeleteEmployee).toBe(false);
    expect(result.current.canTransferEmployee).toBe(false);
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
    // contracts.advance_payment.record_payment и его соседи по apps.contracts
    // сознательно не переведены — тот же повод, по которому backend
    // (apps/hr/legacy_roles.py::DEFERRED_KEYS) не мапит его сам: узел этой
    // области владеет apps.contracts, а не apps.hr. Даже при максимальной
    // глубине на hr этот ключ обязан остаться false, а не превратиться в
    // «пусти всех» по ошибке маппинга.
    getMe.mockResolvedValue(baseMe({
      permissions: { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
      depth: { hr: ['view', 'create', 'edit', 'delete'] },
    }));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasPerm('contracts.advance_payment.record_payment')).toBe(false);
  });

  it('различает «права не загрузились» и «прав нет»', async () => {
    // Оба случая отдают level: null — так и должно быть, отказ в закрытую
    // (докстринг usePermissions). Но это РАЗНЫЕ ситуации: одна — временная
    // сетевая проблема, другая — штатное «доступа нет». `isError` — это и
    // есть отличие; молча схлопнуть их значило бы то самое поведение, из-за
    // которого в usePermissions заведён отдельный признак.
    getMe.mockRejectedValue(new Error('сеть недоступна'));

    const { result } = renderHook(() => useHRLevel(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level).toBeNull();
    expect(result.current.isError).toBe(true);
  });
});
