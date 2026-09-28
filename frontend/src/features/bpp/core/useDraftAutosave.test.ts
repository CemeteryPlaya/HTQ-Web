/**
 * Автосохранение черновика (ТЗ §26.2): каждые 30 с последнее значение формы
 * уходит в `localStorage` и при повторном открытии предлагается к
 * восстановлению; недоступное хранилище форму не роняет.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDraftAutosave } from './useDraftAutosave';

const KEY = 'bpp.draft.test';

type Form = { title: string };

describe('useDraftAutosave', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-27T20:30:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('раз в 30 с пишет последнее значение формы', () => {
    const { rerender } = renderHook(
      ({ value }: { value: Form }) => useDraftAutosave(KEY, value, { enabled: true }),
      { initialProps: { value: { title: 'а' } } },
    );

    act(() => { vi.advanceTimersByTime(29_999); });
    expect(window.localStorage.getItem(KEY)).toBeNull();

    rerender({ value: { title: 'абв' } });
    act(() => { vi.advanceTimersByTime(1); });
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? 'null')).toEqual({
      savedAt: '2026-09-27T20:30:30.000Z',
      value: { title: 'абв' },
    });
  });

  it('выключено — не пишет', () => {
    renderHook(() => useDraftAutosave(KEY, { title: 'а' }, { enabled: false }));
    act(() => { vi.advanceTimersByTime(90_000); });
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('интервал настраивается', () => {
    renderHook(() => useDraftAutosave(KEY, { title: 'а' }, { enabled: true, intervalMs: 1_000 }));
    act(() => { vi.advanceTimersByTime(1_000); });
    expect(window.localStorage.getItem(KEY)).not.toBeNull();
  });

  it('при открытии отдаёт найденный черновик, discard его стирает', () => {
    window.localStorage.setItem(
      KEY, JSON.stringify({ savedAt: '2026-09-27T10:00:00Z', value: { title: 'старое' } }),
    );
    const { result } = renderHook(
      () => useDraftAutosave<Form>(KEY, { title: '' }, { enabled: false }),
    );
    expect(result.current.draft).toEqual({
      savedAt: '2026-09-27T10:00:00Z', value: { title: 'старое' },
    });

    act(() => { result.current.discard(); });
    expect(result.current.draft).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('автосохранение не подменяет предложенный черновик', () => {
    window.localStorage.setItem(
      KEY, JSON.stringify({ savedAt: '2026-09-27T10:00:00Z', value: { title: 'старое' } }),
    );
    const { result } = renderHook(
      () => useDraftAutosave<Form>(KEY, { title: 'новое' }, { enabled: true }),
    );
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(result.current.draft?.value).toEqual({ title: 'старое' });
  });

  it('битая запись в хранилище — черновика нет, а не падение', () => {
    window.localStorage.setItem(KEY, '{не json');
    const { result } = renderHook(
      () => useDraftAutosave<Form>(KEY, { title: '' }, { enabled: false }),
    );
    expect(result.current.draft).toBeNull();
  });

  it('недоступное хранилище не роняет форму', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError');
    });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });

    const { result } = renderHook(
      () => useDraftAutosave<Form>(KEY, { title: 'а' }, { enabled: true }),
    );
    expect(result.current.draft).toBeNull();
    expect(() => act(() => { vi.advanceTimersByTime(30_000); })).not.toThrow();
    expect(() => act(() => { result.current.discard(); })).not.toThrow();
  });
});
