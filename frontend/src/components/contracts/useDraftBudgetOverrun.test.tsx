/**
 * Предупреждение о перерасходе на форме новой оплаты.
 *
 * Главное здесь — арифметика: остаток программы на реальных данных почти
 * всегда ОТРИЦАТЕЛЬНЫЙ и с копейками (-47 905 597,68), и счёт через float или
 * через копейки без знака дал бы на нём неверную сумму перерасхода.
 */
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { contractsApi } from '@/api/contracts';

import { useDraftBudgetOverrun } from './useDraftBudgetOverrun';

vi.mock('@/api/contracts', () => ({ contractsApi: { getBudgetLine: vi.fn() } }));
const getBudgetLine = vi.mocked(contractsApi.getBudgetLine);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function lineWithRemaining(remaining: string) {
  getBudgetLine.mockResolvedValue({ data: { remaining } } as never);
}

const open = { contract_type: 'framework' as const, budget_line_id: 7 };

describe('useDraftBudgetOverrun', () => {
  beforeEach(() => getBudgetLine.mockReset());

  it('warns by how much the payment goes past the remaining budget', async () => {
    lineWithRemaining('1000000.00');
    const { result } = renderHook(() => useDraftBudgetOverrun(open, '1500000,50'), { wrapper });
    await waitFor(() => expect(result.current).toBe('500000.50'));
  });

  it('adds the payment to an already negative remaining, kopecks included', async () => {
    lineWithRemaining('-47905597.68');
    const { result } = renderHook(() => useDraftBudgetOverrun(open, '100.50'), { wrapper });
    await waitFor(() => expect(result.current).toBe('47905698.18'));
  });

  it('stays silent within the limit and at exactly the limit', async () => {
    lineWithRemaining('1000.00');
    const { result } = renderHook(() => useDraftBudgetOverrun(open, '1000'), { wrapper });
    await waitFor(() => expect(getBudgetLine).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('never asks the budget for a standard agreement', () => {
    const standard = { contract_type: 'standard' as const, budget_line_id: 7 };
    const { result } = renderHook(() => useDraftBudgetOverrun(standard, '999999999'), { wrapper });
    expect(result.current).toBeNull();
    expect(getBudgetLine).not.toHaveBeenCalled();
  });
});
