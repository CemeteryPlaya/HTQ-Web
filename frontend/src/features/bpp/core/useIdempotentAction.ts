/**
 * Защита кнопки документа от двойного нажатия и от «второй оплаты» при
 * повторе (ТЗ §05 «кнопка блокируется до ответа», §26.2; Review Focus 5
 * плана этапа 2 A).
 *
 * Два правила:
 * 1. Пока запрос в полёте (`pending`), повторный `run` НЕ шлёт второй запрос,
 *    а возвращает тот же промис. Замок держится в ref, а не только в
 *    состоянии: два клика в одном такте оба увидели бы `pending === false`,
 *    пока React не перерисовал кнопку.
 * 2. Ключ `Idempotency-Key` живёт, пока действие не завершилось ответом
 *    сервера по существу. После 5xx или обрыва сети исход неизвестен —
 *    сервер мог успеть провести переход, — поэтому следующий `run` идёт ТЕМ
 *    ЖЕ ключом, и сервер вернёт результат первого запроса вместо второго
 *    перехода статуса. После успеха или 4xx (сервер ответил и ничего не
 *    сделал либо сделал) — новый ключ: следующий `run` — новое действие.
 *
 * Ошибка пробрасывается вызывающему: показать её — его дело
 * (`reportApiError`), здесь решается только судьба ключа.
 */
import { useCallback, useRef, useState } from 'react';

import { newIdempotencyKey } from '@/api/files';
import { errorStatus } from '@/lib/apiError';

/** Исход неизвестен: сеть оборвалась или сервер упал на полпути. */
export function outcomeUnknown(error: unknown): boolean {
  const status = errorStatus(error);
  return status === undefined || status >= 500;
}

export interface IdempotentAction<T> {
  /** Запустить действие; во время полёта — тот же промис, без запроса. */
  run: () => Promise<T>;
  pending: boolean;
}

export function useIdempotentAction<T>(
  fn: (key: string) => Promise<T>,
): IdempotentAction<T> {
  const [pending, setPending] = useState(false);
  const inFlight = useRef<Promise<T> | null>(null);
  const key = useRef<string | null>(null);
  // Последняя версия `fn` — чтобы `run` оставался стабильным между рендерами
  // и при этом не звал устаревшее замыкание с прошлыми данными формы.
  const latestFn = useRef(fn);
  latestFn.current = fn;

  const run = useCallback((): Promise<T> => {
    if (inFlight.current) return inFlight.current;

    const current = key.current ?? newIdempotencyKey();
    key.current = current;
    setPending(true);

    // Вызов `fn` — через `then`, а не напрямую: синхронный `throw` внутри
    // `fn` иначе снял бы замок раньше, чем промис лёг в `inFlight`, и замок
    // остался бы висеть на уже отклонённом промисе навсегда.
    const request = Promise.resolve()
      .then(() => latestFn.current(current))
      .then(
        (result) => {
          key.current = null;
          return result;
        },
        (error: unknown) => {
          if (!outcomeUnknown(error)) key.current = null;
          throw error;
        },
      )
      .finally(() => {
        inFlight.current = null;
        setPending(false);
      });
    inFlight.current = request;
    return request;
  }, []);

  return { run, pending };
}
