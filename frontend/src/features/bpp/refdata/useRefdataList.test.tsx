/**
 * Выбор в новых документах читает справочник без архива (`?active=1`,
 * ТЗ §18), экран справочника — целиком; это разные ключи кэша.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { refdataKeys } from './api';
import { useActiveRefdata, useRefdataList } from './useRefdataList';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
);

beforeEach(() => {
  get.mockReset();
  get.mockResolvedValue({ data: [] });
});

describe('useActiveRefdata', () => {
  it('выбор в документе — ?active=1', async () => {
    const { result } = renderHook(() => useActiveRefdata('currencies'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith('refdata/v1/currencies', { params: { active: '1' } });
  });

  it('статьи и группы — тем же параметром', async () => {
    const { result } = renderHook(() => useActiveRefdata('articleGroups'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith('refdata/v1/article-groups', { params: { active: '1' } });
  });
});

describe('useRefdataList', () => {
  it('экран справочника — без параметра, архив в ответе', async () => {
    const { result } = renderHook(() => useRefdataList('uoms'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith('refdata/v1/uoms', { params: undefined });
  });
});

describe('refdataKeys', () => {
  it('полный список и список без архива — разные ключи под общим префиксом', () => {
    const all = refdataKeys.list('countries');
    const active = refdataKeys.list('countries', { active: true });
    expect(all).not.toEqual(active);
    const prefix = refdataKeys.collection('countries');
    expect(all.slice(0, prefix.length)).toEqual([...prefix]);
    expect(active.slice(0, prefix.length)).toEqual([...prefix]);
  });
});
