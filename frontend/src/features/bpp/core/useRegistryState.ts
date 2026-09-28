/**
 * Состояние реестра модуля БЗО (ТЗ §19: пагинация 50 из 25/50/100, серверная
 * сортировка и фильтрация, быстрый поиск, сохранение пользовательских
 * фильтров и набора колонок).
 *
 * Сохраняется в `localStorage` под ключом `bpp:registry:<ключ реестра>`:
 * фильтры, скрытые колонки, размер страницы и сортировка — то, что человек
 * настраивает под себя. Номер страницы и быстрый поиск — нет: вернувшись в
 * реестр из меню, человек ждёт его начало, а не третью страницу позавчерашнего
 * поиска. Их место — адрес страницы (`?page=`, `?q=`, опция `url`): «Назад»
 * со строки документа возвращает туда же, откуда ушли, ссылкой на выборку
 * можно поделиться, а переход из меню (адрес без параметров) начинает
 * реестр сначала. Адрес правится с `replace` — листание страниц не
 * засоряет историю браузера.
 *
 * Быстрый поиск и текстовые фильтры уходят в запрос с задержкой
 * `INPUT_DEBOUNCE_MS` после последнего нажатия: поле показывает набранное
 * сразу, а реестр не перечитывается на каждую букву. Выпадающие фильтры,
 * даты, сортировка и страницы применяются сразу.
 *
 * В запрос и в сохранённые настройки попадают только фильтры, объявленные
 * реестром (`filterKeys`): фильтр, убранный из экрана, не должен молча
 * сужать выборку из старой записи `localStorage`.
 *
 * Хранилище может отказать (приватный режим, переполнение, запрет сайта) —
 * каждое обращение в try/catch: без него реестр работает, просто не помнит
 * настройки. Это штатная деградация, а не подмена данных, поэтому мимо
 * `lib/fallback` (см. «Что через него НЕ проходит» в CLAUDE.md).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export const PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 50;

/** Значение фильтра «не задан» у выпадающих фильтров. */
export const FILTER_ALL = 'all';

/** Задержка применения быстрого поиска и текстовых фильтров. */
export const INPUT_DEBOUNCE_MS = 300;

export interface RegistrySort {
  field: string;
  desc: boolean;
}

interface Persisted {
  pageSize: PageSize;
  sort: RegistrySort | null;
  filters: Record<string, string>;
  hidden: string[];
}

export const storageKeyFor = (registryKey: string) => `bpp:registry:${registryKey}`;

/** Параметры адреса страницы, в которых живут номер страницы и поиск. */
export const URL_PAGE = 'page';
export const URL_SEARCH = 'q';

/** Адрес страницы — то, что отдаёт `useSearchParams` роутера. Хук от
 * роутера не зависит: реестр передаёт пару сам (и без неё хук работает). */
export interface RegistryUrl {
  params: URLSearchParams;
  setParams: (
    next: (current: URLSearchParams) => URLSearchParams,
    options?: { replace?: boolean },
  ) => void;
}

const pageFromUrl = (params: URLSearchParams): number => {
  const value = Number(params.get(URL_PAGE));
  return Number.isInteger(value) && value > 1 ? value : 1;
};
const searchFromUrl = (params: URLSearchParams): string => params.get(URL_SEARCH) ?? '';

const isPageSize = (value: unknown): value is PageSize =>
  PAGE_SIZES.includes(value as PageSize);

function readPersisted(registryKey: string, filterKeys?: readonly string[]): Partial<Persisted> {
  try {
    const raw = window.localStorage.getItem(storageKeyFor(registryKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<Persisted> | null;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Partial<Persisted> = {};
    if (isPageSize(parsed.pageSize)) out.pageSize = parsed.pageSize;
    if (parsed.sort && typeof parsed.sort.field === 'string') {
      out.sort = { field: parsed.sort.field, desc: Boolean(parsed.sort.desc) };
    }
    if (parsed.filters && typeof parsed.filters === 'object') {
      out.filters = Object.fromEntries(
        Object.entries(parsed.filters).filter(([k, v]) =>
          typeof v === 'string' && (!filterKeys || filterKeys.includes(k))),
      ) as Record<string, string>;
    }
    if (Array.isArray(parsed.hidden)) {
      out.hidden = parsed.hidden.filter((v): v is string => typeof v === 'string');
    }
    return out;
  } catch {
    return {};
  }
}

function writePersisted(registryKey: string, value: Persisted): void {
  try {
    window.localStorage.setItem(storageKeyFor(registryKey), JSON.stringify(value));
  } catch {
    // Хранилище недоступно — настройки живут до ухода со страницы.
  }
}

export interface RegistryStateOptions {
  /** Сортировка по умолчанию (пока человек не выбрал свою). */
  defaultSort?: RegistrySort | null;
  /** Колонки, скрытые по умолчанию (пока человек не настроил набор). */
  defaultHidden?: string[];
  /** Имя параметра быстрого поиска: реестр заявок B понимает только `search`,
   * реестр контрагентов — и `q`, и `search`. */
  searchParam?: string;
  /** Ключи фильтров, объявленных реестром; остальные из `localStorage` и
   * из состояния в запрос не идут. `undefined` — без ограничения. */
  filterKeys?: readonly string[];
  /** Держать номер страницы и поиск в адресе страницы (`?page=`, `?q=`). */
  url?: RegistryUrl;
}

export interface SetFilterOptions {
  /** Применить с задержкой (текстовое поле), а не сразу. */
  debounce?: boolean;
}

export interface RegistryState {
  page: number;
  pageSize: PageSize;
  sort: RegistrySort | null;
  /** Набранный текст поиска (для поля ввода; в запрос — с задержкой). */
  search: string;
  /** Фильтры как в полях ввода (в запрос текстовые — с задержкой). */
  filters: Record<string, string>;
  hidden: string[];
  setPage: (page: number) => void;
  setPageSize: (size: PageSize) => void;
  /** Клик по заголовку: по возрастанию → по убыванию → по возрастанию. */
  toggleSort: (field: string) => void;
  setSearch: (text: string) => void;
  setFilter: (key: string, value: string, options?: SetFilterOptions) => void;
  resetFilters: () => void;
  toggleColumn: (key: string) => void;
  /** Параметры запроса реестра (без пустых фильтров). */
  params: Record<string, string | number>;
  /** Те же параметры без страницы — для экспорта «текущей выборки». */
  selectionParams: Record<string, string>;
}

/** `{field, desc}` → параметр `sort` сервера: `-created_at` / `number`. */
export const sortParam = (sort: RegistrySort | null): string | undefined =>
  sort ? `${sort.desc ? '-' : ''}${sort.field}` : undefined;

export function useRegistryState(
  registryKey: string,
  {
    defaultSort = null, defaultHidden = [], searchParam = 'search', filterKeys, url,
  }: RegistryStateOptions = {},
): RegistryState {
  // Стабильный ключ набора фильтров: массив из пропсов новый на каждом рендере.
  const filterKeysKey = filterKeys ? filterKeys.join('|') : null;
  const [persisted] = useState(() => readPersisted(registryKey, filterKeys));
  const [page, setPageRaw] = useState(() => (url ? pageFromUrl(url.params) : 1));
  const [pageSize, setPageSizeRaw] = useState<PageSize>(persisted.pageSize ?? DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState<RegistrySort | null>(persisted.sort ?? defaultSort);
  const [search, setSearchRaw] = useState(() => (url ? searchFromUrl(url.params) : ''));
  const [appliedSearch, setAppliedSearch] = useState(search);
  const [filters, setFiltersRaw] = useState<Record<string, string>>(persisted.filters ?? {});
  const [appliedFilters, setAppliedFilters] = useState<Record<string, string>>(filters);
  const [hidden, setHidden] = useState<string[]>(persisted.hidden ?? defaultHidden);

  // Текущие фильтры — ещё и в ref: отложенное применение должно взять
  // последнее набранное, а не значение на момент нажатия.
  const filtersRef = useRef(filters);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const filtersTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = (timer: { current: ReturnType<typeof setTimeout> | null }) => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => () => {
    cancel(searchTimer);
    cancel(filtersTimer);
  }, []);

  useEffect(() => {
    writePersisted(registryKey, { pageSize, sort, filters, hidden });
  }, [registryKey, pageSize, sort, filters, hidden]);

  // Страница и поиск ⇄ адрес. `written` — что адрес несёт с нашей же записи:
  // своё эхо из адреса обратно в состояние не принимается, иначе поиск,
  // применённый через паузу, затёр бы буквы, набранные после неё.
  const urlPage = url ? pageFromUrl(url.params) : null;
  const urlSearch = url ? searchFromUrl(url.params) : null;
  const written = useRef({ page: urlPage, search: urlSearch });
  const setUrlRef = useRef(url?.setParams);
  setUrlRef.current = url?.setParams;

  // Адрес → состояние: «Назад»/«Вперёд» браузера, переход из меню на тот же
  // реестр без параметров.
  useEffect(() => {
    if (urlPage === null || urlPage === written.current.page) return;
    written.current.page = urlPage;
    setPageRaw(urlPage);
  }, [urlPage]);
  useEffect(() => {
    if (urlSearch === null || urlSearch === written.current.search) return;
    written.current.search = urlSearch;
    cancel(searchTimer);
    setSearchRaw(urlSearch);
    setAppliedSearch(urlSearch);
  }, [urlSearch]);

  // Состояние → адрес: применённый поиск (не каждая буква) и страница.
  useEffect(() => {
    const setParams = setUrlRef.current;
    if (!setParams) return;
    const text = appliedSearch.trim();
    if (written.current.page === page && written.current.search === text) return;
    written.current = { page, search: text };
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (page > 1) next.set(URL_PAGE, String(page)); else next.delete(URL_PAGE);
      if (text) next.set(URL_SEARCH, text); else next.delete(URL_SEARCH);
      return next;
    }, { replace: true });
  }, [page, appliedSearch]);

  // Любая смена выборки начинает её с первой страницы: седьмой страницы
  // новой выборки может не быть вовсе.
  const setPage = useCallback((next: number) => setPageRaw(Math.max(1, next)), []);
  const setPageSize = useCallback((size: PageSize) => {
    setPageSizeRaw(size);
    setPageRaw(1);
  }, []);
  const toggleSort = useCallback((field: string) => {
    setSort((current) =>
      current?.field === field ? { field, desc: !current.desc } : { field, desc: false });
    setPageRaw(1);
  }, []);
  const setSearch = useCallback((text: string) => {
    setSearchRaw(text);
    cancel(searchTimer);
    searchTimer.current = setTimeout(() => {
      searchTimer.current = null;
      setAppliedSearch(text);
      setPageRaw(1);
    }, INPUT_DEBOUNCE_MS);
  }, []);
  const setFilter = useCallback((key: string, value: string, options?: SetFilterOptions) => {
    const next = { ...filtersRef.current };
    if (!value || value === FILTER_ALL) delete next[key];
    else next[key] = value;
    filtersRef.current = next;
    setFiltersRaw(next);
    const apply = () => {
      filtersTimer.current = null;
      setAppliedFilters(filtersRef.current);
      setPageRaw(1);
    };
    cancel(filtersTimer);
    if (options?.debounce) filtersTimer.current = setTimeout(apply, INPUT_DEBOUNCE_MS);
    else apply();
  }, []);
  const resetFilters = useCallback(() => {
    cancel(searchTimer);
    cancel(filtersTimer);
    filtersRef.current = {};
    setFiltersRaw({});
    setAppliedFilters({});
    setSearchRaw('');
    setAppliedSearch('');
    setPageRaw(1);
  }, []);
  const toggleColumn = useCallback((key: string) => {
    setHidden((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key]);
  }, []);

  const selectionParams = useMemo(() => {
    const allowed = filterKeysKey === null ? null : filterKeysKey.split('|');
    const out: Record<string, string> = Object.fromEntries(
      Object.entries(appliedFilters).filter(([key]) => !allowed || allowed.includes(key)),
    );
    const order = sortParam(sort);
    if (order) out.sort = order;
    const text = appliedSearch.trim();
    if (text) out[searchParam] = text;
    return out;
  }, [appliedFilters, filterKeysKey, sort, appliedSearch, searchParam]);

  const params = useMemo(
    () => ({ ...selectionParams, page, page_size: pageSize }),
    [selectionParams, page, pageSize],
  );

  return {
    page, pageSize, sort, search, filters, hidden,
    setPage, setPageSize, toggleSort, setSearch, setFilter, resetFilters, toggleColumn,
    params, selectionParams,
  };
}
