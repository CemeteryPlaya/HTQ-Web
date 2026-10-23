/**
 * Фильтры доски — в адресе (`?q=&label=&member=…`), чтобы ссылкой можно было
 * поделиться и «назад» возвращал прежний вид. Пишутся с `replace`: набор
 * фильтра не плодит записи истории (образец — `features/bpp/core/useRegistryState.ts`).
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { EMPTY_FILTERS, type BoardFilters } from '../types';

const LISTS = ['label', 'member', 'due', 'completion', 'activity'] as const;

export function readFilters(params: URLSearchParams): BoardFilters {
  const list = (name: string) =>
    (params.get(name) ?? '').split(',').map((part) => part.trim()).filter(Boolean);
  return {
    q: params.get('q') ?? '',
    label: list('label'),
    member: list('member'),
    due: list('due'),
    completion: list('completion'),
    activity: list('activity'),
    new: params.get('new') === '1',
    hideEmpty: params.get('compact') === '1',
  };
}

export function writeFilters(current: URLSearchParams, filters: BoardFilters): URLSearchParams {
  const next = new URLSearchParams(current);
  if (filters.q) next.set('q', filters.q); else next.delete('q');
  for (const name of LISTS) {
    if (filters[name].length) next.set(name, filters[name].join(',')); else next.delete(name);
  }
  if (filters.new) next.set('new', '1'); else next.delete('new');
  if (filters.hideEmpty) next.set('compact', '1'); else next.delete('compact');
  return next;
}

export function activeFilterCount(filters: BoardFilters): number {
  return (filters.q ? 1 : 0) + LISTS.reduce((sum, name) => sum + filters[name].length, 0)
    + (filters.new ? 1 : 0);
}

export function useBoardFilters() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => readFilters(params), [params]);
  const setFilters = useCallback(
    (next: BoardFilters) => setParams((current) => writeFilters(current, next), { replace: true }),
    [setParams],
  );
  // Сброс оставляет вид («скрывать пустые колонки»): это не условие отбора.
  const reset = useCallback(
    () => setFilters({ ...EMPTY_FILTERS, hideEmpty: filters.hideEmpty }),
    [setFilters, filters.hideEmpty],
  );
  return { filters, setFilters, reset, active: activeFilterCount(filters) };
}
