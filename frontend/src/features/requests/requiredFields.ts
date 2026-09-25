/**
 * Какие обязательные поля формы ещё не заполнены.
 *
 * Зеркало серверной проверки (`approvals/services/value_validation.py`):
 * смотрятся поля ВЕРХНЕГО уровня с `required`, пустым считается `null`,
 * пустая строка и пустой список (у повторяемой группы это «ни одной
 * строки»). Поля внутри строк группы сервер не проверяет — и здесь не
 * проверяются: клиент, который запрещает больше сервера, врёт о правилах.
 *
 * Нужно затем, чтобы человек узнавал о незаполненном поле от ФОРМЫ, а не
 * из 422 после нажатия «Отправить». Возвращаются подписи полей — именно их
 * человек видит на экране.
 */

import type { FormField, FormSchema } from '@/features/requests/types';

function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value as object).length === 0;
  return false;
}

/** Все поля формы с путями: `key` и `группа.key` у неповторяемой группы.
 *  Внутрь повторяемой не идём — у её строк нет одного значения. */
export function fieldPaths(schema: FormSchema | undefined): Record<string, FormField> {
  const out: Record<string, FormField> = {};
  for (const field of schema?.fields ?? []) {
    out[field.key] = field;
    const group = field as FormField & { fields?: FormField[]; repeatable?: boolean };
    if (field.type === 'group' && group.repeatable === false) {
      for (const sub of group.fields ?? []) out[`${field.key}.${sub.key}`] = sub;
    }
  }
  return out;
}

function valueAt(values: Record<string, unknown>, path: string): unknown {
  const [head, ...rest] = path.split('.');
  const value = values[head];
  if (rest.length === 0) return value;
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)[rest[0]]
    : undefined;
}

function label(schema: FormSchema, path: string): string {
  const [head, tail] = path.split('.');
  const top = schema.fields.find((f) => f.key === head);
  if (!top) return path;
  if (!tail) return top.label;
  const group = top as FormField & { fields?: FormField[] };
  const sub = group.fields?.find((f) => f.key === tail);
  return sub ? `${top.label} → ${sub.label}` : top.label;
}

/**
 * Нарушение `must_equal` внутри поля верхнего уровня — текст для человека
 * или `null`. Зеркало `value_validation.mismatch_in`: сравниваем, только
 * когда ОБА значения есть (пустое — забота обязательности), и по числу, а
 * не по строке: `1000 === '1000.00'` ложно.
 */
export function mismatchIn(
  schema: FormSchema | undefined,
  fieldKey: string,
  values: Record<string, unknown>,
): string | null {
  if (!schema) return null;
  const paths = fieldPaths(schema);
  for (const [path, field] of Object.entries(paths)) {
    if (path.split('.')[0] !== fieldKey) continue;
    const target = field.must_equal;
    if (!target || !(target in paths)) continue;
    const mine = valueAt(values, path);
    const theirs = valueAt(values, target);
    if (isBlank(mine) || isBlank(theirs)) continue;
    if (Number(mine) !== Number(theirs)) {
      return `«${label(schema, path)}» (${mine}) не совпадает с `
        + `«${label(schema, target)}» (${theirs}) — суммы должны быть одинаковыми`;
    }
  }
  return null;
}

export function missingRequired(
  schema: FormSchema | undefined,
  values: Record<string, unknown>,
): string[] {
  if (!schema) return [];
  return schema.fields
    // Поля согласующего с инициатора не спрашиваются — как и на сервере.
    .filter((field: FormField) => field.filled_by !== 'approver')
    .filter((field: FormField) => field.required && isBlank(values[field.key]))
    .map((field) => field.label);
}

/** Готовая причина для `SubmitForApproval.blockedReason` — или `null`, если
 *  отправлять можно. */
export function blockedByRequired(
  schema: FormSchema | undefined,
  values: Record<string, unknown>,
): string | null {
  const missing = missingRequired(schema, values);
  if (missing.length === 0) return null;
  return missing.length === 1
    ? `Заполните поле «${missing[0]}»`
    : `Заполните поля: ${missing.map((label) => `«${label}»`).join(', ')}`;
}
