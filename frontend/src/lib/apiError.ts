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
 * - **400** — введённое не подходит: чужой домен у ящика, неверный текущий
 *   пароль, занятый логин. Причина в тексте, и без неё пользователю нечего
 *   исправлять.
 * - **403** — про права, но текст двоякий: см. `PERMISSION_GATE_DETAIL`.
 * - **502** — внешняя система отказала, и её ответ и есть причина: «Mailcow
 *   error: …», «провайдер не вернул email», «media-service unavailable»
 *   (`apps/mail/views.py`, `apps/hr/services/department_file_service.py`).
 *   502 от nginx (упавший upstream) сюда не попадает: там HTML без `detail`,
 *   и `errorDetail` вернёт null, то есть покажется запасная фраза.
 * - **503** — модуль выключен целиком (`manage.py service <name> --off`).
 *
 * Всё остальное сводится к одной запасной фразе: разбирать сетевые сбои по
 * отдельности здесь нечего.
 */

import { toast } from 'sonner';
import type { ExternalToast } from 'sonner';
import i18next from '@/i18n';

/**
 * У ошибки ДВЕ формы, и это не мелочь: на 5xx `response` до сюда не доезжает.
 *
 * Интерцептор `api/client.ts` сворачивает всё от 500 и выше в обычный
 * `Error(serverMsg)` с полями `status`/`isServerError` — объект axios с
 * `response` при этом теряется. Пока разбор смотрел только на `response`,
 * ответ сервера на 502/503 не читался вообще: `AdminMailboxes` показывал на
 * отказ mailcow буквальное слово «Error», хотя причина («Mailcow error:
 * mailbox already exists») лежала в `message`.
 */
interface ApiErrorShape {
  response?: {
    status?: number;
    data?: { detail?: unknown };
  };
  /** Свёрнутая форма 5xx из `api/client.ts`. */
  status?: number;
  isServerError?: boolean;
  message?: string;
}

/** Текст `detail`, если бэкенд прислал именно текст. */
export function errorDetail(error: unknown): string | null {
  const shape = error as ApiErrorShape;
  const detail = shape?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === 'string');
    if (messages.length > 0) return messages.join('; ');
  }
  // Свёрнутая 5xx: `message` уже содержит `detail` сервера (его достаёт
  // `extractServerErrorMessage`) либо готовую фразу про внутреннюю ошибку.
  if (shape?.isServerError && typeof shape.message === 'string' && shape.message) {
    return shape.message;
  }
  return null;
}

export function errorStatus(error: unknown): number | undefined {
  const shape = error as ApiErrorShape;
  return shape?.response?.status ?? (shape?.isServerError ? shape.status : undefined);
}

/** Коды, у которых `detail` бэкенда — уже готовое объяснение для человека. */
const EXPLAINED_BY_BACKEND = [400, 409, 422, 403, 503, 413, 415, 502];

/**
 * Машинные строки сторожей прав — их показывать нельзя.
 *
 * У 403 текст бывает двух сортов, и разница видна невооружённым глазом:
 *
 * - фраза, написанная для человека: «Самостоятельное подключение ящиков
 *   отключено — обратитесь к администратору» (`apps/mail/views.py`);
 * - вывод декоратора прав: «Forbidden», «Missing permission:
 *   hr.card.finance.edit», «Senior HR access required» (`htqweb/http.py`,
 *   `apps/hr/views.py`). Это опознавательный знак для лога, а не объяснение,
 *   и русскоязычному сотруднику он не говорит ничего.
 *
 * Перечисляем ВТОРОЙ сорт: он конечен и порождается несколькими декораторами,
 * тогда как первый пишется каждый раз заново и списком не задаётся.
 */
const PERMISSION_GATE_DETAIL = [
  /^Forbidden$/,
  /^Missing permission: /,
  /access required$/,
  /^Admin privileges required$/,
  /^Department access denied$/,
];

/**
 * Текст бэкенда, но ТОЛЬКО если по статусу он объясняет причину.
 *
 * Отдельно от `reportApiError`, потому что показать причину можно не только
 * тостом: `MailboxPasswordDialog` дописывает к ней пояснение про «сервер не
 * различает неверный пароль и отсутствующий ящик». Без этой функции такое
 * место обходило бы политику статусов и печатало бы внутренности 500-й.
 */
export function explainedDetail(error: unknown): string | null {
  const status = errorStatus(error);
  if (status === undefined || !EXPLAINED_BY_BACKEND.includes(status)) return null;
  return errorDetail(error);
}

/**
 * Показать ошибку тостом: текст бэкенда, если он объясняет причину.
 *
 * `options` — те же настройки, что принимает `toast.error`. Нужны ровно для
 * одного: почтовые ошибки IMAP/SMTP длинные, и их показывают дольше обычного
 * (`{ duration: 12_000 }`) — прочитать «AUTHENTICATIONFAILED» за три секунды
 * нельзя. Без этого параметра такие места остались бы в обход утилиты.
 */
export function reportApiError(
  error: unknown,
  fallback: string,
  options?: ExternalToast,
): void {
  const detail = explainedDetail(error);
  if (detail && PERMISSION_GATE_DETAIL.some((pattern) => pattern.test(detail))) {
    toast.error(
      i18next.t('common.errors.forbidden', 'Недостаточно прав для этого действия'),
      options,
    );
    return;
  }
  toast.error(detail ?? fallback, options);
}
