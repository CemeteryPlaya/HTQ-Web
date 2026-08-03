/**
 * Разбор ответа `{"detail": ...}` в текст для пользователя.
 *
 * Общая утилита, а не деталь одного домена: конверт ошибки у всех аппок
 * одинаковый (`htqweb.http.api_view`), поэтому и разбор один. Жила в
 * `components/signoff/`, хотя ею уже пользовались договоры и HR.
 *
 * Коды несут разный смысл и сведены сюда, чтобы не разъезжаться по страницам:
 *
 * - **409** — запрос корректен по форме, но противоречит состоянию данных:
 *   вес должности занят, диапазон уровня пересекается с соседним, объект уже
 *   на согласовании, решение уже принято. Текст бэкенда и есть объяснение —
 *   показываем его как есть, а не «проверьте поля».
 * - **422** — нарушение схемы: либо список Pydantic-ошибок, либо готовая
 *   фраза сервиса (например, «Вес 999 вне диапазона уровня L1 (1-20)»).
 * - **413/415** — пайплайн загрузки media_files отверг документ: больше
 *   25 МБ или не PDF. Отдельные коды, потому что исправлять надо разное.
 * - **403** — ответ ТОЛЬКО про права.
 * - **503** — модуль выключен целиком (`manage.py service <name> --off`).
 *
 * Всё остальное сводится к одной запасной фразе: разбирать сетевые сбои по
 * отдельности здесь нечего.
 */

import { toast } from 'sonner';

interface ApiErrorShape {
  response?: {
    status?: number;
    data?: { detail?: unknown };
  };
}

/** Текст `detail`, если бэкенд прислал именно текст. */
export function errorDetail(error: unknown): string | null {
  const detail = (error as ApiErrorShape)?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === 'string');
    if (messages.length > 0) return messages.join('; ');
  }
  return null;
}

export function errorStatus(error: unknown): number | undefined {
  return (error as ApiErrorShape)?.response?.status;
}

/** Коды, у которых `detail` бэкенда — уже готовое объяснение для человека. */
const EXPLAINED_BY_BACKEND = [409, 422, 403, 503, 413, 415];

/** Показать ошибку тостом: текст бэкенда, если он объясняет причину. */
export function reportApiError(error: unknown, fallback: string): void {
  const status = errorStatus(error);
  const detail = errorDetail(error);
  if (detail && status !== undefined && EXPLAINED_BY_BACKEND.includes(status)) {
    toast.error(detail);
    return;
  }
  toast.error(fallback);
}
