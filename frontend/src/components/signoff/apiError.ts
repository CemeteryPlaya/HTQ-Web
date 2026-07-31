/**
 * Разбор ошибки согласования в текст для пользователя.
 *
 * Коды здесь несут разный смысл и сведены в одно место, чтобы не
 * разъезжаться по страницам:
 *
 * - **409** — запрос корректен по форме, но противоречит состоянию данных:
 *   маршрут не настроен, объект уже на согласовании, запрос адресован
 *   другому, решение уже принято, все согласующие этапа отключены. Текст
 *   бэкенда и есть объяснение — показываем его как есть, а не «проверьте
 *   поля».
 * - **422** — нарушение схемы, приходит списком Pydantic-ошибок.
 * - **413/415** — пайплайн загрузки media_files отверг приложенный документ:
 *   больше 25 МБ или не PDF. Отдельные коды, потому что исправлять надо
 *   разное, и текст бэкенда называет что именно.
 * - **403** — ответ ТОЛЬКО про права (например, отзыв чужого согласования).
 * - **503** — модуль согласования выключен целиком
 *   (`manage.py service signoff --off`).
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
