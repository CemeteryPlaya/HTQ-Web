/**
 * Разбор поля `changes` журнала модуля (`AuditLog`, ТЗ §25.2) в строки
 * «поле — было — стало».
 *
 * Сервисы модуля пишут изменения тремя способами, и вкладка понимает все:
 * - `{поле: [было, стало]}` — точечная правка (контрагент, настройки);
 * - `{before: {…}, after: {…}}` — снимок до и после (заявка, подотчёт,
 *   строки бюджета); показываются только поля, что изменились;
 * - `{поле: значение}` — факт события (создание, сумма при отправке): только
 *   «стало».
 */
import i18next from '@/i18n';

export interface ChangeRow {
  field: string;
  before?: string;
  after?: string;
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** Значение ячейки строкой: вложенное — компактным JSON, пустое — «—». */
export const showValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') {
    return value ? i18next.t('bpp.history.yes', 'да') : i18next.t('bpp.history.no', 'нет');
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function changeRows(changes: Record<string, unknown> | null | undefined): ChangeRow[] {
  if (!isPlainObject(changes)) return [];
  const keys = Object.keys(changes);
  if (keys.length === 2 && isPlainObject(changes.before) && isPlainObject(changes.after)) {
    const before = changes.before;
    const after = changes.after;
    const fields = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    return fields
      .filter((field) => !same(before[field], after[field]))
      .map((field) => ({
        field, before: showValue(before[field]), after: showValue(after[field]),
      }));
  }
  return keys.map((field) => {
    const value = changes[field];
    if (Array.isArray(value) && value.length === 2) {
      return { field, before: showValue(value[0]), after: showValue(value[1]) };
    }
    if (isPlainObject(value) && 'before' in value && 'after' in value) {
      return { field, before: showValue(value.before), after: showValue(value.after) };
    }
    return { field, after: showValue(value) };
  });
}
