/**
 * Реестр модуля БЗО (ТЗ §19, мастер-план A2.1): общая таблица для реестров
 * бюджетов, заявок, договоров, счетов и справочников модуля.
 *
 * - данные — конверт реестров B `{items, total, page, page_size, totals?}`;
 *   сортировка, фильтры, поиск и страницы считает СЕРВЕР (строки, доступные
 *   пользователю, тоже фильтрует он — ТЗ §19);
 * - пагинация 25/50/100, по умолчанию 50; фильтры, набор колонок, размер
 *   страницы и сортировка помнятся в `localStorage` (`useRegistryState`),
 *   номер страницы и быстрый поиск — в адресе (`?page=`, `?q=`): возврат со
 *   строки документа кнопкой «Назад» не сбрасывает место в реестре. Голый
 *   адрес реестра — «открыли из меню», место сбрасывается; поэтому ссылка
 *   «К списку» на форме документа строится хуком `useRegistryBackHref(base)`
 *   из `registryBack.ts`: открывая строку, реестр кладёт свой `?page=&q=` в
 *   состояние перехода, и ссылка возвращает туда же. Формам исполнителя B —
 *   тот же хук, а не голый `<Link to={BASE}>`;
 * - флажки и массовые действия с результатом по каждой строке: сколько
 *   прошло и какие отклонены с причиной (ТЗ §10.5);
 * - итоговая строка — по `totals` сервера, то есть по всей выборке, а не по
 *   странице;
 * - «Экспорт» — xlsx текущей выборки (`registryExport.ts`, задача 6);
 * - строка ведёт на форму документа (`rowHref`): первая видимая колонка —
 *   настоящая ссылка (клавиатура, «открыть в новой вкладке»), клик мышью по
 *   остальной строке — тот же переход;
 * - быстрый поиск и текстовые фильтры применяются через 300 мс после
 *   последнего нажатия; смена выборки или страницы снимает отметки строк
 *   (отмеченные строки новой страницы не видны — массовое действие по ним
 *   было бы вслепую); страница за пределами сократившейся выборки
 *   прижимается к последней.
 */
import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Columns3, Download, Search,
} from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Pagination, PaginationContent, PaginationItem } from '@/components/ui/pagination';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { registryOpenState } from './registryBack';
import { exportRegistry } from './registryExport';
import type {
  BulkOutcome, RegistryBulkAction, RegistryColumn, RegistryFilter, RegistryPage,
} from './registryTypes';
import {
  FILTER_ALL, PAGE_SIZES, useRegistryState, type PageSize, type RegistrySort,
} from './useRegistryState';

interface Props<Row extends { id: string }> {
  /** Ключ реестра — часть ключа `localStorage` и кеша запросов. */
  registryKey: string;
  /** Адрес реестра относительно `/api/` (`apiPath('bpp', 'requests')`). */
  endpoint: string;
  columns: RegistryColumn<Row>[];
  filters?: RegistryFilter[];
  bulkActions?: RegistryBulkAction[];
  /** Имя файла экспорта без расширения; `undefined` — кнопки «Экспорт» нет. */
  exportName?: string;
  /** Параметр быстрого поиска сервера (`search` у заявок B). */
  searchParam?: string;
  searchPlaceholder?: string;
  /** Есть ли у ручки быстрый поиск (по умолчанию да). `false` — поля поиска
   * нет: поле, которое ничего не ищет, хуже его отсутствия. */
  searchable?: boolean;
  defaultSort?: RegistrySort | null;
  defaultHidden?: string[];
  /** Куда ведёт клик по строке (форма документа). */
  rowHref?: (row: Row) => string;
  /** Как назвать строку в итогах массового действия (номер документа). */
  rowLabel?: (row: Row) => string;
  /** Правее кнопки «Экспорт» — «Создать» и т.п. */
  toolbarExtra?: ReactNode;
  /** Держать страницу и поиск в адресе (по умолчанию да). Выключать, если
   * на одной странице два реестра: параметры адреса у них общие. */
  syncUrl?: boolean;
}

const cellValue = (row: object, key: string): ReactNode => {
  const value = (row as Record<string, unknown>)[key];
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};

const sortField = <Row,>(column: RegistryColumn<Row>): string | null =>
  column.sortable === true ? column.key : column.sortable || null;

export function BppRegistry<Row extends { id: string }>({
  registryKey, endpoint, columns, filters = [], bulkActions = [], exportName,
  searchParam, searchPlaceholder, searchable = true, defaultSort, defaultHidden, rowHref,
  rowLabel, toolbarExtra, syncUrl = true,
}: Props<Row>) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [urlParams, setUrlParams] = useSearchParams();
  const filterKeys = useMemo(() => filters.map((filter) => filter.key), [filters]);
  const state = useRegistryState(registryKey, {
    defaultSort, defaultHidden, searchParam, filterKeys,
    url: syncUrl ? { params: urlParams, setParams: setUrlParams } : undefined,
  });
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [outcome, setOutcome] = useState<(BulkOutcome & { action: string }) | null>(null);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const queryKey = ['bpp', 'registry', registryKey, endpoint, state.params] as const;
  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey,
    queryFn: () =>
      api.get<RegistryPage<Row>>(endpoint, { params: state.params }).then((r) => r.data),
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));

  // Выборка сократилась (строки ушли в другой статус, их удалили) — третьей
  // страницы из двух нет: прижимаемся к последней, а не показываем пустоту.
  const { page, setPage } = state;
  useEffect(() => {
    if (data && page > pageCount) setPage(pageCount);
  }, [data, page, pageCount, setPage]);

  // Отметки живут в пределах одной выборки и страницы: после смены фильтра,
  // сортировки, поиска или страницы отмеченные строки больше не видны.
  const paramsKey = JSON.stringify(state.params);
  useEffect(() => {
    setSelected((current) => (current.size === 0 ? current : new Set()));
  }, [paramsKey]);
  const visible = columns.filter((column) => column.required || !state.hidden.includes(column.key));
  const hasBulk = bulkActions.length > 0;
  const labels = useMemo(
    () => new Map(items.map((row) => [row.id, rowLabel ? rowLabel(row) : row.id])),
    [items, rowLabel],
  );
  const totals = data?.totals;
  const showTotals = !!totals && visible.some((column) => column.total);

  const allOnPage = items.length > 0 && items.every((row) => selected.has(row.id));
  const toggleAll = () => {
    setSelected((current) => {
      const next = new Set(current);
      if (allOnPage) items.forEach((row) => next.delete(row.id));
      else items.forEach((row) => next.add(row.id));
      return next;
    });
  };
  const toggleRow = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const runBulk = async (action: RegistryBulkAction) => {
    const ids = [...selected];
    if (ids.length === 0) return;
    setRunningAction(action.key);
    setOutcome(null);
    try {
      const result = await action.run(ids);
      setOutcome({ ...result, action: action.label });
      // Прошедшие строки снимаются с отметки, отклонённые остаются — их
      // можно поправить и повторить.
      setSelected(new Set(result.failed.map((row) => row.id)));
      await queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', registryKey] });
    } catch (error) {
      reportApiError(error, action.errorText
        ?? t('bpp.registry.bulkFailed', 'Не удалось выполнить действие'));
    } finally {
      setRunningAction(null);
    }
  };

  const runExport = async () => {
    if (!exportName) return;
    setExporting(true);
    try {
      const result = await exportRegistry(endpoint, state.selectionParams, exportName);
      if (result.kind === 'queued') {
        toast.info(t('bpp.registry.exportQueued', 'Выгрузка готовится, ссылка придёт уведомлением'));
      }
    } catch (error) {
      // Своя ошибка «реестр не умеет выгрузку» — без статуса HTTP, и
      // `reportApiError` заменил бы её текст запасной фразой.
      if ((error as Error)?.name === 'ExportNotSupportedError') {
        toast.error((error as Error).message);
      } else {
        reportApiError(error, t('bpp.registry.exportFailed', 'Не удалось выгрузить реестр'));
      }
    } finally {
      setExporting(false);
    }
  };

  const sortIcon = (field: string) => {
    if (state.sort?.field !== field) return <ArrowUpDown className="h-3.5 w-3.5 opacity-40" />;
    return state.sort.desc
      ? <ArrowDown className="h-3.5 w-3.5" />
      : <ArrowUp className="h-3.5 w-3.5" />;
  };
  const ariaSort = (field: string | null): 'ascending' | 'descending' | 'none' | undefined => {
    if (!field) return undefined;
    if (state.sort?.field !== field) return 'none';
    return state.sort.desc ? 'descending' : 'ascending';
  };

  const colSpan = visible.length + (hasBulk ? 1 : 0);

  // Место в реестре уходит с переходом на форму: ссылка «К списку» там
  // (`useRegistryBackHref`) вернёт на ту же страницу и поиск. Без синхронизации
  // с адресом строка запроса реестру не принадлежит — не передаём.
  const openState = syncUrl ? registryOpenState(location.search) : undefined;

  // Клик мышью по строке — переход; клик по самой ссылке и клик с
  // модификатором (новая вкладка) браузер обрабатывает сам.
  const onRowClick = (row: Row) => (event: MouseEvent<HTMLTableRowElement>) => {
    if (!rowHref) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if ((event.target as HTMLElement).closest('a, button, input, [role="checkbox"]')) return;
    navigate(rowHref(row), { state: openState });
  };
  const cellContent = (row: Row, column: RegistryColumn<Row>, index: number): ReactNode => {
    const content = column.render ? column.render(row) : cellValue(row, column.key);
    if (!rowHref || index !== 0) return content;
    return (
      <Link to={rowHref(row)} state={openState} className="font-medium text-primary hover:underline">
        {content}
      </Link>
    );
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        {searchable && (
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={state.search}
              onChange={(event) => state.setSearch(event.target.value)}
              placeholder={searchPlaceholder
                ?? t('bpp.registry.searchPlaceholder', 'Поиск по номеру и наименованию')}
              aria-label={t('bpp.registry.search', 'Быстрый поиск')}
              className="pl-8"
            />
          </div>
        )}

        {filters.map((filter) => (
          <div key={filter.key} className="min-w-40">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor={`bpp-filter-${filter.key}`}>
              {filter.label}
            </label>
            {filter.kind === 'select' ? (
              <Select
                value={state.filters[filter.key] ?? FILTER_ALL}
                onValueChange={(value) => state.setFilter(filter.key, value)}
              >
                <SelectTrigger id={`bpp-filter-${filter.key}`} aria-label={filter.label}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FILTER_ALL}>{t('bpp.registry.filterAll', 'Все')}</SelectItem>
                  {(filter.options ?? []).map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : filter.kind === 'date' ? (
              <DateInput
                id={`bpp-filter-${filter.key}`}
                aria-label={filter.label}
                value={state.filters[filter.key] ?? ''}
                onChange={(value) => state.setFilter(filter.key, value)}
              />
            ) : (
              <Input
                id={`bpp-filter-${filter.key}`}
                aria-label={filter.label}
                value={state.filters[filter.key] ?? ''}
                onChange={(event) =>
                  state.setFilter(filter.key, event.target.value, { debounce: true })}
              />
            )}
          </div>
        ))}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {(Object.keys(state.filters).length > 0 || state.search) && (
            <Button variant="ghost" size="sm" onClick={state.resetFilters}>
              {t('bpp.registry.resetFilters', 'Сбросить фильтры')}
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Columns3 className="mr-1.5 h-4 w-4" />
                {t('bpp.registry.columns', 'Колонки')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('bpp.registry.columnsTitle', 'Показывать колонки')}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {columns.filter((column) => !column.required).map((column) => (
                <DropdownMenuCheckboxItem
                  key={column.key}
                  checked={!state.hidden.includes(column.key)}
                  onCheckedChange={() => state.toggleColumn(column.key)}
                  onSelect={(event) => event.preventDefault()}
                >
                  {column.title}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          {exportName !== undefined && (
            <Button variant="outline" size="sm" onClick={runExport} disabled={exporting}>
              <Download className="mr-1.5 h-4 w-4" />
              {t('bpp.registry.export', 'Экспорт')}
            </Button>
          )}
          {toolbarExtra}
        </div>
      </div>

      {hasBulk && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          <span>{t('bpp.registry.selected', 'Отмечено: {{count}}', { count: selected.size })}</span>
          {bulkActions.map((action) => (
            <Button
              key={action.key}
              size="sm"
              variant="secondary"
              disabled={runningAction !== null}
              onClick={() => runBulk(action)}
            >
              {action.label}
            </Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            {t('bpp.registry.clearSelection', 'Снять отметки')}
          </Button>
        </div>
      )}

      {outcome && (
        <div role="status" className="rounded-lg border px-3 py-2 text-sm">
          <p className="font-medium">
            {outcome.action}:{' '}
            {t('bpp.registry.bulkDone', 'выполнено — {{ok}}, отклонено — {{failed}}', {
              ok: outcome.ok.length, failed: outcome.failed.length,
            })}
          </p>
          {outcome.failed.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-destructive">
              {outcome.failed.map((row) => (
                <li key={row.id}>
                  <span className="font-medium">{labels.get(row.id) ?? row.id}</span>: {row.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className={cn('overflow-x-auto rounded-lg border bg-card', isFetching && 'opacity-80')}>
        <Table>
          <TableHeader>
            <TableRow>
              {hasBulk && (
                <TableHead className="w-10">
                  <Checkbox
                    checked={allOnPage}
                    onCheckedChange={toggleAll}
                    aria-label={t('bpp.registry.selectPage', 'Отметить все на странице')}
                  />
                </TableHead>
              )}
              {visible.map((column) => {
                const field = sortField(column);
                return (
                  <TableHead
                    key={column.key}
                    aria-sort={ariaSort(field)}
                    className={cn(column.align === 'right' && 'text-right')}
                  >
                    {field ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-foreground"
                        onClick={() => state.toggleSort(field)}
                      >
                        {column.title}
                        {sortIcon(field)}
                      </button>
                    ) : column.title}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [0, 1, 2].map((row) => (
                <TableRow key={row}>
                  <TableCell colSpan={colSpan}><Skeleton className="h-6 w-full" /></TableCell>
                </TableRow>
              ))
            ) : isError ? (
              <TableRow>
                <TableCell colSpan={colSpan} className="py-8 text-center text-destructive">
                  {t('bpp.registry.loadError', 'Не удалось загрузить реестр. Обновите страницу.')}
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={colSpan} className="py-10 text-center text-muted-foreground">
                  {t('bpp.registry.empty', 'Ничего не найдено. Измените фильтры или поиск.')}
                </TableCell>
              </TableRow>
            ) : (
              items.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={selected.has(row.id) ? 'selected' : undefined}
                  className={cn(rowHref && 'cursor-pointer')}
                  onClick={rowHref ? onRowClick(row) : undefined}
                >
                  {hasBulk && (
                    <TableCell className="w-10" onClick={(event) => event.stopPropagation()}>
                      <Checkbox
                        checked={selected.has(row.id)}
                        onCheckedChange={() => toggleRow(row.id)}
                        aria-label={t('bpp.registry.selectRow', 'Отметить {{label}}', {
                          label: labels.get(row.id) ?? row.id,
                        })}
                      />
                    </TableCell>
                  )}
                  {visible.map((column, index) => (
                    <TableCell
                      key={column.key}
                      className={cn(column.align === 'right' && 'text-right tabular-nums')}
                    >
                      {cellContent(row, column, index)}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
          {showTotals && totals && items.length > 0 && (
            <TableFooter>
              <TableRow>
                {hasBulk && <TableCell />}
                {visible.map((column, index) => (
                  <TableCell
                    key={column.key}
                    className={cn('font-semibold', column.align === 'right' && 'text-right tabular-nums')}
                  >
                    {column.total
                      ? column.total(totals)
                      : index === 0 ? t('bpp.registry.totalRow', 'Итого по выборке') : null}
                  </TableCell>
                ))}
              </TableRow>
            </TableFooter>
          )}
        </Table>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted-foreground">
          {t('bpp.registry.total', 'Всего: {{count}}', { count: total })}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">{t('bpp.registry.pageSize', 'Строк на странице')}</span>
          <Select
            value={String(state.pageSize)}
            onValueChange={(value) => state.setPageSize(Number(value) as PageSize)}
          >
            <SelectTrigger className="h-8 w-20" aria-label={t('bpp.registry.pageSize', 'Строк на странице')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((size) => (
                <SelectItem key={size} value={String(size)}>{size}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Pagination className="mx-0 ml-auto w-auto">
          <PaginationContent>
            <PaginationItem>
              <Button
                variant="ghost"
                size="sm"
                disabled={state.page <= 1}
                onClick={() => state.setPage(state.page - 1)}
                aria-label={t('bpp.registry.prevPage', 'Предыдущая страница')}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            </PaginationItem>
            <PaginationItem>
              <span className="px-2">
                {t('bpp.registry.pageOf', 'Страница {{page}} из {{pages}}', {
                  page: Math.min(state.page, pageCount), pages: pageCount,
                })}
              </span>
            </PaginationItem>
            <PaginationItem>
              <Button
                variant="ghost"
                size="sm"
                disabled={state.page >= pageCount}
                onClick={() => state.setPage(state.page + 1)}
                aria-label={t('bpp.registry.nextPage', 'Следующая страница')}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </section>
  );
}

export default BppRegistry;
