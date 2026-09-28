/**
 * Состояние реестра модуля (ТЗ §19; задача 8): пагинация 25/50/100 (по
 * умолчанию 50), сортировка, фильтры и скрытые колонки помнятся в
 * `localStorage` под ключом реестра; страница и быстрый поиск — нет, они в
 * адресе страницы (опция `url`).
 */
import { createElement, type ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_PAGE_SIZE, FILTER_ALL, INPUT_DEBOUNCE_MS, storageKeyFor, useRegistryState,
} from './useRegistryState';

const KEY = 'requests';

describe('useRegistryState', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('состояние по умолчанию', () => {
    const { result } = renderHook(() => useRegistryState(KEY));
    expect(result.current.page).toBe(1);
    expect(result.current.pageSize).toBe(DEFAULT_PAGE_SIZE);
    expect(result.current.sort).toBeNull();
    expect(result.current.filters).toEqual({});
    expect(result.current.hidden).toEqual([]);
    expect(result.current.params).toEqual({ page: 1, page_size: DEFAULT_PAGE_SIZE });
  });

  it('смена страницы и размера страницы уходит в параметры запроса', () => {
    const { result } = renderHook(() => useRegistryState(KEY));
    act(() => result.current.setPage(3));
    expect(result.current.page).toBe(3);
    expect(result.current.params.page).toBe(3);

    act(() => result.current.setPageSize(100));
    // Смена размера страницы возвращает на первую — старая страница может не существовать.
    expect(result.current.page).toBe(1);
    expect(result.current.pageSize).toBe(100);
    expect(result.current.params.page_size).toBe(100);
  });

  it('сортировка: клик по полю — по возрастанию, повтор — по убыванию, снова — по возрастанию', () => {
    const { result } = renderHook(() => useRegistryState(KEY));
    act(() => result.current.setPage(2));

    act(() => result.current.toggleSort('number'));
    expect(result.current.sort).toEqual({ field: 'number', desc: false });
    expect(result.current.params.sort).toBe('number');
    expect(result.current.page).toBe(1); // смена сортировки тоже возвращает на первую страницу

    act(() => result.current.toggleSort('number'));
    expect(result.current.sort).toEqual({ field: 'number', desc: true });
    expect(result.current.params.sort).toBe('-number');

    act(() => result.current.toggleSort('other'));
    expect(result.current.sort).toEqual({ field: 'other', desc: false });
  });

  it('поиск уходит в выбранный параметр запроса через паузу и сбрасывает страницу', () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useRegistryState(KEY, { searchParam: 'q' }));
      act(() => result.current.setPage(4));
      act(() => result.current.setSearch('  догов'));
      act(() => result.current.setSearch('  договор №7  '));
      // Поле показывает набранное сразу, запрос — ещё нет.
      expect(result.current.search).toBe('  договор №7  ');
      expect(result.current.params.q).toBeUndefined();
      expect(result.current.page).toBe(4);

      act(() => { vi.advanceTimersByTime(INPUT_DEBOUNCE_MS); });
      expect(result.current.params.q).toBe('договор №7');
      expect(result.current.page).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('текстовый фильтр — с паузой, выпадающий — сразу', () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useRegistryState(KEY));
      act(() => result.current.setFilter('name', 'бет', { debounce: true }));
      act(() => result.current.setFilter('name', 'бетон', { debounce: true }));
      expect(result.current.filters).toEqual({ name: 'бетон' });
      expect(result.current.params.name).toBeUndefined();

      act(() => { vi.advanceTimersByTime(INPUT_DEBOUNCE_MS); });
      expect(result.current.params.name).toBe('бетон');

      act(() => result.current.setFilter('status', 'draft'));
      expect(result.current.params.status).toBe('draft');
    } finally {
      vi.useRealTimers();
    }
  });

  it('в запрос идут только объявленные фильтры, даже из старого localStorage', () => {
    window.localStorage.setItem(storageKeyFor(KEY), JSON.stringify({
      filters: { status: 'draft', removed_filter: 'x' },
    }));
    const { result } = renderHook(() => useRegistryState(KEY, { filterKeys: ['status'] }));
    expect(result.current.filters).toEqual({ status: 'draft' });
    expect(result.current.params).toEqual({ status: 'draft', page: 1, page_size: DEFAULT_PAGE_SIZE });
  });

  it('фильтр: значение FILTER_ALL снимает фильтр, а не хранит его пустым', () => {
    const { result } = renderHook(() => useRegistryState(KEY));
    act(() => result.current.setFilter('status', 'draft'));
    expect(result.current.filters).toEqual({ status: 'draft' });
    expect(result.current.params.status).toBe('draft');

    act(() => result.current.setFilter('status', FILTER_ALL));
    expect(result.current.filters).toEqual({});
    expect(result.current.params.status).toBeUndefined();
  });

  it('resetFilters очищает фильтры, поиск и страницу разом', () => {
    const { result } = renderHook(() => useRegistryState(KEY));
    act(() => {
      result.current.setFilter('status', 'draft');
      result.current.setSearch('текст');
      result.current.setPage(5);
    });
    act(() => result.current.resetFilters());
    expect(result.current.filters).toEqual({});
    expect(result.current.search).toBe('');
    expect(result.current.page).toBe(1);
  });

  it('скрытая колонка остаётся скрытой после перемонтирования (localStorage)', () => {
    const { result, unmount } = renderHook(() => useRegistryState(KEY));
    act(() => result.current.toggleColumn('created_at'));
    expect(result.current.hidden).toEqual(['created_at']);
    unmount();

    const remounted = renderHook(() => useRegistryState(KEY));
    expect(remounted.result.current.hidden).toEqual(['created_at']);

    act(() => remounted.result.current.toggleColumn('created_at'));
    expect(remounted.result.current.hidden).toEqual([]);
  });

  it('размер страницы, сортировка и фильтры тоже переживают перемонтирование; страница и поиск — нет', () => {
    const { result, unmount } = renderHook(() => useRegistryState(KEY));
    act(() => {
      result.current.setPageSize(100);
      result.current.toggleSort('number');
      result.current.setFilter('status', 'draft');
      result.current.setPage(3);
      result.current.setSearch('что-то');
    });
    unmount();

    const remounted = renderHook(() => useRegistryState(KEY));
    expect(remounted.result.current.pageSize).toBe(100);
    expect(remounted.result.current.sort).toEqual({ field: 'number', desc: false });
    expect(remounted.result.current.filters).toEqual({ status: 'draft' });
    expect(remounted.result.current.page).toBe(1);
    expect(remounted.result.current.search).toBe('');
  });

  it('ключ реестра — часть ключа localStorage, реестры друг друга не путают', () => {
    const a = renderHook(() => useRegistryState('requests'));
    act(() => a.result.current.toggleColumn('x'));
    const b = renderHook(() => useRegistryState('budgets'));
    expect(b.result.current.hidden).toEqual([]);
    expect(JSON.parse(window.localStorage.getItem(storageKeyFor('requests')) ?? 'null').hidden)
      .toEqual(['x']);
    expect(JSON.parse(window.localStorage.getItem(storageKeyFor('budgets')) ?? 'null').hidden)
      .toEqual([]);
  });

  it('недоступное хранилище не роняет реестр', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => { throw new DOMException('denied', 'SecurityError'); };
    try {
      const { result } = renderHook(() => useRegistryState(KEY));
      expect(result.current.hidden).toEqual([]);
      expect(() => act(() => result.current.toggleColumn('x'))).not.toThrow();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});

describe('useRegistryState — страница и поиск в адресе', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  function renderWithUrl(entry: string) {
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(MemoryRouter, { initialEntries: [entry] }, children);
    return renderHook(() => {
      const [params, setParams] = useSearchParams();
      const location = useLocation();
      const navigate = useNavigate();
      const state = useRegistryState(KEY, { url: { params, setParams } });
      return { state, location, navigate };
    }, { wrapper });
  }

  it('страница и поиск читаются из адреса', () => {
    const { result } = renderWithUrl('/bpp/requests?page=3&q=бетон');
    expect(result.current.state.page).toBe(3);
    expect(result.current.state.search).toBe('бетон');
    expect(result.current.state.params).toMatchObject({ page: 3, search: 'бетон' });
  });

  it('мусор в ?page= — первая страница', () => {
    const { result } = renderWithUrl('/bpp/requests?page=abc');
    expect(result.current.state.page).toBe(1);
  });

  it('страница и применённый поиск пишутся в адрес, чужие параметры не трогаются', () => {
    vi.useFakeTimers();
    try {
      const { result } = renderWithUrl('/bpp/requests?tab=mine');
      act(() => result.current.state.setPage(2));
      expect(result.current.location.search).toBe('?tab=mine&page=2');

      act(() => result.current.state.setSearch('дого'));
      // До паузы адрес не меняется: не на каждую букву.
      expect(result.current.location.search).toBe('?tab=mine&page=2');
      act(() => { vi.advanceTimersByTime(INPUT_DEBOUNCE_MS); });
      // Поиск вернул на первую страницу — `page` из адреса ушёл.
      expect(new URLSearchParams(result.current.location.search).get('q')).toBe('дого');
      expect(new URLSearchParams(result.current.location.search).get('page')).toBeNull();
      expect(new URLSearchParams(result.current.location.search).get('tab')).toBe('mine');
    } finally {
      vi.useRealTimers();
    }
  });

  it('переход на реестр без параметров (из меню) начинает его сначала', () => {
    const { result } = renderWithUrl('/bpp/requests?page=4&q=бетон');
    act(() => result.current.navigate('/bpp/requests'));
    expect(result.current.state.page).toBe(1);
    expect(result.current.state.search).toBe('');
    expect(result.current.state.params).toEqual({ page: 1, page_size: DEFAULT_PAGE_SIZE });
  });

  it('набранное после применения поиска не затирается эхом адреса', () => {
    vi.useFakeTimers();
    try {
      const { result } = renderWithUrl('/bpp/requests');
      act(() => result.current.state.setSearch('бет'));
      act(() => { vi.advanceTimersByTime(INPUT_DEBOUNCE_MS); });
      act(() => result.current.state.setSearch('бетон'));
      expect(result.current.state.search).toBe('бетон');
      act(() => { vi.advanceTimersByTime(INPUT_DEBOUNCE_MS); });
      expect(result.current.state.params.search).toBe('бетон');
      expect(new URLSearchParams(result.current.location.search).get('q')).toBe('бетон');
    } finally {
      vi.useRealTimers();
    }
  });
});
