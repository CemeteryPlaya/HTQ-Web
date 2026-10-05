/**
 * `useContractsFreeze` (A6.2): спрашивает сервер только с токеном и на
 * поддомене компании — хук стоит в шапке, то есть и на публичных страницах.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { contractsApi } from '@/api/contracts';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { useContractsFreeze } from './useContractsFreeze';

const token = vi.fn<() => string | null>(() => 'jwt');
const company = vi.fn<(host: string) => string | null>(() => 'htq');
vi.mock('@/lib/auth/profileStorage', () => ({ getAccessToken: () => token() }));
vi.mock('@/lib/auth/companySwitch', () => ({ companyFromHost: (host: string) => company(host) }));
vi.mock('@/api/contracts', () => ({ contractsApi: { getFreeze: vi.fn() } }));

const getFreeze = vi.mocked(contractsApi.getFreeze);

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  getFreeze.mockReset();
  token.mockReturnValue('jwt');
  company.mockReturnValue('htq');
});

describe('useContractsFreeze', () => {
  it('заморожен — флаг, дата и основание с сервера', async () => {
    getFreeze.mockResolvedValue({
      data: { frozen: true, frozen_at: '2026-10-01T10:00:00Z', comment: 'перенос сверен' },
    } as Awaited<ReturnType<typeof contractsApi.getFreeze>>);
    const { result } = renderHook(() => useContractsFreeze(), { wrapper });
    await waitFor(() => expect(result.current.frozen).toBe(true));
    expect(result.current.frozenAt).toBe('2026-10-01T10:00:00Z');
    expect(result.current.comment).toBe('перенос сверен');
  });

  it('без токена — не спрашивает и не заморожен', () => {
    token.mockReturnValue(null);
    const { result } = renderHook(() => useContractsFreeze(), { wrapper });
    expect(getFreeze).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ frozen: false, isLoading: false });
  });

  it('на голом домене — не спрашивает', () => {
    company.mockReturnValue(null);
    renderHook(() => useContractsFreeze(), { wrapper });
    expect(getFreeze).not.toHaveBeenCalled();
  });

  it('active=false — не спрашивает', () => {
    renderHook(() => useContractsFreeze(false), { wrapper });
    expect(getFreeze).not.toHaveBeenCalled();
  });
});
