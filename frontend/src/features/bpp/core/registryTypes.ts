/**
 * Контракт реестра модуля БЗО (ТЗ §19) — типы, общие для `BppRegistry`,
 * `useRegistryState` и экранов подмодулей.
 */
import type { ReactNode } from 'react';

/** Конверт реестров B: `{items, total, page, page_size}` плюс `totals` —
 * итоги по ВСЕЙ выборке (не по странице), если реестр их считает. */
export interface RegistryPage<Row> {
  items: Row[];
  total: number;
  page: number;
  page_size: number;
  totals?: Record<string, unknown>;
}

export interface RegistryColumn<Row> {
  /** Ключ колонки и (по умолчанию) поле строки. */
  key: string;
  /** Заголовок — уже переведённый (`t('bpp.<…>', 'Русский')`). */
  title: string;
  /** Поле сортировки сервера; `true` — совпадает с `key`. Без него — не сортируется. */
  sortable?: boolean | string;
  /** Колонку нельзя скрыть (номер документа). */
  required?: boolean;
  align?: 'left' | 'right';
  /** Ячейка; по умолчанию — значение поля строкой. */
  render?: (row: Row) => ReactNode;
  /** Ячейка итоговой строки по `totals` сервера. */
  total?: (totals: Record<string, unknown>) => ReactNode;
}

export interface RegistryFilterOption {
  value: string;
  label: string;
}

/** Серверный фильтр: `key` — имя параметра запроса. */
export interface RegistryFilter {
  key: string;
  label: string;
  kind: 'select' | 'text' | 'date';
  /** Для `select` — значения; пункт «Все» реестр добавляет сам. */
  options?: RegistryFilterOption[];
}

/** Итог массового действия по строкам (ТЗ §10.5: «список успешных и
 * отклонённых с причиной»). Экран переводит ответ своей ручки в эту форму. */
export interface BulkOutcome {
  ok: string[];
  failed: { id: string; reason: string }[];
}

export interface RegistryBulkAction {
  key: string;
  label: string;
  /** `null` — человек передумал в своём диалоге (комментарий, дата):
   * ничего не выполнено, итога нет, отметки остаются. */
  run: (ids: string[]) => Promise<BulkOutcome | null>;
  /** Запасной текст тоста, если ручка упала целиком. */
  errorText?: string;
}

/** «Сейчас у» (ТЗ §16.2) — поле `current_holders` строк реестров B. */
export interface CurrentHolders {
  stage: string;
  users: { id: number; name: string }[];
  position: string | null;
  since: string;
  no_executor: boolean;
}
