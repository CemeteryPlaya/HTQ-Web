/**
 * Текст отказа ручек задач для человека.
 *
 * Правила видимости и прав задач (канбан-доски, этап 1) отвечают конвертом
 * `{detail, code}` (`htqweb.errors.DomainError`): `code` — стабильный ключ
 * (`task_transfer_forbidden`, `task_claim_unavailable`, …), по нему берём
 * перевод `tasks.errors.<code>`. Код, которого словарь не знает (новое
 * правило сервера раньше нового фронта), показывает `detail` сервера, а
 * ответ без кода разбирает общий `lib/apiError` по статусу.
 */
import type { TFunction } from 'i18next';
import { toast } from 'sonner';

import { errorCode, explainedDetail, reportApiError } from '@/lib/apiError';

export function taskErrorText(error: unknown, t: TFunction, fallback: string): string {
  const code = errorCode(error);
  const detail = explainedDetail(error) ?? fallback;
  if (!code) return detail;
  return t(`tasks.errors.${code}`, { defaultValue: detail });
}

/** То же тостом; ответ без кода — по правилам `reportApiError`. */
export function reportTaskError(error: unknown, t: TFunction, fallback: string): void {
  // Архив (`company_archived`) уже объяснил `api/client.ts` — `reportApiError`
  // второй тост не покажет, поэтому такой отказ тоже идёт через него.
  if (!errorCode(error) || (error as { archivedReported?: boolean })?.archivedReported) {
    reportApiError(error, fallback);
    return;
  }
  toast.error(taskErrorText(error, t, fallback));
}
