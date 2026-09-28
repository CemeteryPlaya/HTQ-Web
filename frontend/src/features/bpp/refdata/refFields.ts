/**
 * Описание колонок архивируемого справочника (`ArchivableTable`) — отдельно
 * от компонента: react-refresh требует, чтобы файл компонента экспортировал
 * только компоненты.
 */
import type { ReactNode } from 'react';

/** Значение «не выбрано» для необязательного выпадающего списка: Radix
 * `Select` не принимает пустую строку значением пункта. */
export const NONE_OPTION = '__none__';

/** Значение поля диалога → для сервера: пусто и «не выбрано» — `null`. */
export const optionalValue = (value: string | undefined): string | null =>
  value === undefined || value.trim() === '' || value === NONE_OPTION ? null : value.trim();

export interface RefFieldOption {
  value: string;
  label: string;
}

export interface RefField<R> {
  key: string;
  label: string;
  /** `false` — поле задаётся только при создании (код, группа статьи):
   * колонка есть, в диалоге правки поля нет. PATCH-схема сервера его и не
   * принимает. */
  editable?: boolean;
  /** По умолчанию поле обязательно при создании. */
  optional?: boolean;
  maxLength?: number;
  /** Выпадающий список вместо текстового поля. */
  options?: RefFieldOption[];
  /** Своя отрисовка ячейки (например, имя группы вместо её id). */
  render?: (row: R) => ReactNode;
}

export interface RefRowBase {
  id: string;
  can_edit: boolean;
  is_active?: boolean;
}
