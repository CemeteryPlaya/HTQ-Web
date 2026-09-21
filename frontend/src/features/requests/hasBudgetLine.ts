import type { FormSchema } from '@/features/requests/types';

/** Есть ли в форме заполненная строка бюджета (виджет `budget_line_ref`) —
 *  верхний уровень или строка повторяемой группы, как ищет и бэкенд. */
export function hasBudgetLine(schema: FormSchema | undefined, values: Record<string, unknown>): boolean {
  if (!schema) return false;
  const isId = (v: unknown) => typeof v === 'number' && Number.isInteger(v);
  for (const field of schema.fields) {
    if (field.type === 'budget_line_ref' && isId(values[field.key])) return true;
    if (field.type === 'group') {
      const rows = values[field.key];
      if (!Array.isArray(rows)) continue;
      for (const row of rows) {
        if (row && typeof row === 'object' && field.fields.some(
          (child) => child.type === 'budget_line_ref' && isId((row as Record<string, unknown>)[child.key]),
        )) return true;
      }
    }
  }
  return false;
}
