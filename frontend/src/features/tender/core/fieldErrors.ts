/**
 * Ошибки по полям из ответа бэкенда тендерного модуля. Конвертов два:
 * - отказ сервиса — `{detail, code, fields: [{field, message}]}`: имена
 *   полей тела (`project_id`, `items[0].qty`), текст — готовый для человека;
 * - проверка ТИПОВ платформой (`api_view` + pydantic) — 422
 *   `{detail: [{type, loc, msg}]}` без `code`: не-UUID, не-дата, не-число.
 *   `loc` сводится к тому же имени поля, а `msg` (английский) заменяется
 *   запасным русским текстом.
 *
 * Тост для второго случая — свой (`reportFormError`): общий
 * `reportApiError` склеил бы английские `msg` pydantic в одно сообщение.
 */
import { toast } from 'sonner';

import { reportApiError } from '@/lib/apiError';

interface ErrorShape {
  response?: { data?: { detail?: unknown; fields?: unknown } };
}

type Loc = (string | number)[];

/** `['body', 'items', 0, 'qty']` → `items[0].qty`. */
function locToField(loc: Loc): string {
  const parts = loc[0] === 'body' ? loc.slice(1) : loc;
  return parts.reduce<string>((path, part) => (
    typeof part === 'number' ? `${path}[${part}]` : path ? `${path}.${part}` : String(part)
  ), '');
}

/** Ошибка типов pydantic: `detail` — массив с `loc`. */
export function isTypeError(error: unknown): boolean {
  const detail = (error as ErrorShape)?.response?.data?.detail;
  return Array.isArray(detail) && detail.some((item) => Array.isArray((item as { loc?: unknown })?.loc));
}

/** `{поле: текст}`; `typeMessage` — текст для ошибок типов pydantic. */
export function fieldErrorsOf(error: unknown, typeMessage: string): Record<string, string> {
  const data = (error as ErrorShape)?.response?.data;
  const out: Record<string, string> = {};
  if (Array.isArray(data?.fields)) {
    for (const item of data.fields as { field?: unknown; message?: unknown }[]) {
      if (typeof item?.field === 'string' && typeof item.message === 'string') out[item.field] = item.message;
    }
  }
  if (Array.isArray(data?.detail)) {
    for (const item of data.detail as { loc?: unknown }[]) {
      if (Array.isArray(item?.loc)) {
        const field = locToField(item.loc as Loc);
        if (field) out[field] = typeMessage;
      }
    }
  }
  return out;
}

/**
 * Раскладка для формы с позициями: `items[i].x` → ключ i-й строки формы
 * (`keys[i]`), остальное — по именам полей. Первая ошибка строки побеждает.
 */
export function itemFieldErrors(errors: Record<string, string>, keys: string[]): {
  fields: Record<string, string>;
  items: Record<string, string>;
} {
  const fields: Record<string, string> = {};
  const items: Record<string, string> = {};
  for (const [field, message] of Object.entries(errors)) {
    const match = /^items\[(\d+)\]/.exec(field);
    const key = match ? keys[Number(match[1])] : undefined;
    if (key) {
      if (!(key in items)) items[key] = message;
    } else {
      fields[field] = message;
    }
  }
  return { fields, items };
}

/** Тост отказа: ошибка типов — общий русский текст, прочее — `reportApiError`. */
export function reportFormError(error: unknown, fallback: string, typeText: string): void {
  if (isTypeError(error)) {
    toast.error(typeText, undefined);
    return;
  }
  reportApiError(error, fallback);
}
