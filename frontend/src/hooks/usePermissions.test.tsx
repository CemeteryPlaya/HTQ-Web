/**
 * Права текущего пользователя на фронте.
 *
 * Проверяется одно: интерфейс сравнивает уровни ровно по тому же правилу, что
 * и бэкенд (§3 спеки — «не ниже требуемого»), и не выдаёт доступ там, где
 * ответа о правах нет. Второе важнее первого: пустой ответ приходит штатно —
 * вне контекста компании (§4.5), — и трактовать его как «пока не знаем,
 * покажем» значило бы показать разделы, которых сервер не даст.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ACCESS_ME_FIXTURE, ACCESS_ME_NO_COMPANY } from '@/api/access.fixture';
import type { AccessMe } from '@/types/access';

import { usePermissions } from './usePermissions';

const getMe = vi.fn<[], Promise<AccessMe>>();

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

beforeEach(() => {
  getMe.mockReset();
});

describe('usePermissions', () => {
  it('отдаёт уровень модуля из ответа сервера', async () => {
    getMe.mockResolvedValue(ACCESS_ME_FIXTURE);

    const { result } = renderHook(() => usePermissions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level('tasks')).toBe('write');
    expect(result.current.level('hr')).toBe('admin');
  });

  it('сравнивает по правилу «не ниже требуемого»', async () => {
    getMe.mockResolvedValue(ACCESS_ME_FIXTURE);

    const { result } = renderHook(() => usePermissions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.atLeast('tasks', 'read')).toBe(true);
    expect(result.current.atLeast('tasks', 'write')).toBe(true);
    expect(result.current.atLeast('tasks', 'admin')).toBe(false);
  });

  it('отдаёт область модуля, а для модуля без доступа — null', async () => {
    getMe.mockResolvedValue(ACCESS_ME_FIXTURE);

    const { result } = renderHook(() => usePermissions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.scope('tasks')).toEqual({ kind: 'department', id: 3 });
    expect(result.current.scope('messenger')).toBeNull();
  });

  it('ничего не разрешает на пустом ответе вне контекста компании', async () => {
    getMe.mockResolvedValue(ACCESS_ME_NO_COMPANY);

    const { result } = renderHook(() => usePermissions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.company).toBeNull();
    expect(result.current.level('hr')).toBe('none');
    expect(result.current.atLeast('hr', 'read')).toBe(false);
  });

  it('ничего не разрешает, пока ответ не получен', async () => {
    // Пока права неизвестны, интерфейс обязан молчать: показать раздел и
    // отобрать его после загрузки — хуже, чем не показать вовсе.
    getMe.mockReturnValue(new Promise<AccessMe>(() => {}));

    const { result } = renderHook(() => usePermissions(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.atLeast('hr', 'read')).toBe(false);
  });

  it('ничего не разрешает, когда запрос упал', async () => {
    getMe.mockRejectedValue(new Error('сеть недоступна'));

    const { result } = renderHook(() => usePermissions(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.atLeast('hr', 'read')).toBe(false);
  });
});
