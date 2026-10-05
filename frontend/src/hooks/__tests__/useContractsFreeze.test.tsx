import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Счётчик и ответ — обычной функцией: отклонённый промис из vi.fn() vitest
// пересоздаёт и оставляет необработанным.
let calls = 0;
let answer: () => Promise<unknown> = () => Promise.resolve({ data: {} });
vi.mock('@/api/contracts', () => ({
  contractsApi: { getFreeze: () => { calls += 1; return answer(); } },
}));
vi.mock('@/lib/auth/profileStorage', () => ({ getAccessToken: () => 'token' }));
vi.mock('@/lib/auth/companySwitch', () => ({ companyFromHost: () => 'htq' }));

import { useContractsFreeze } from '../useContractsFreeze';

function wrapper() {
  const client = new QueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('useContractsFreeze', () => {
  beforeEach(() => { calls = 0; });

  it('503 при выключенном модуле — «не заморожен», и второй хук не перезапрашивает', async () => {
    answer = () => Promise.reject(Object.assign(new Error('503'), { response: { status: 503 } }));
    const w = wrapper();
    const first = renderHook(() => useContractsFreeze(), { wrapper: w });
    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    expect(first.result.current.frozen).toBe(false);

    const second = renderHook(() => useContractsFreeze(), { wrapper: w });
    await waitFor(() => expect(second.result.current.isLoading).toBe(false));
    expect(calls).toBe(1);
  });

  it('заморожен — флаг приходит', async () => {
    answer = () => Promise.resolve({ data: { frozen: true, frozen_at: '2026-10-01', comment: 'c' } });
    const { result } = renderHook(() => useContractsFreeze(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.frozen).toBe(true));
  });
});
