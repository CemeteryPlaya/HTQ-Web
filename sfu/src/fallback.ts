/**
 * Подмена значения, которую слышно. Третье зеркало одного механизма:
 * `backend/htqweb/fallback.py` и `frontend/src/lib/fallback.ts` — те же
 * понятия, тот же формат строки, та же ось среды.
 *
 * Два режима, ось — `HTQ_ENV`:
 *
 * - `production` / `staging` — подмена происходит, участник конференции
 *   ничего не замечает, но в лог уходит строка `FALLBACK …`, а счётчик
 *   `sfu_fallback_total` растёт;
 * - `development` — подмены НЕТ: летит `FallbackNotAllowed`.
 *
 * Явная `FALLBACK_MODE` (`strict` | `log`) перебивает вывод из среды.
 *
 * Счётчик здесь только объявляется — на реестр его кладёт `metrics.ts`
 * (`registerFallbackMetrics`). Так этот модуль ничего не импортирует из
 * metrics.ts, и цикла import'ов не возникает: metrics.ts пользуется
 * `fallback()` наравне с остальными.
 */
import { Counter } from 'prom-client';

export type FallbackMode = 'log' | 'strict';

export class FallbackNotAllowed extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = 'FallbackNotAllowed';
  }
}

/** Счётчик подмен. Регистрируется из metrics.ts, см. докстринг модуля. */
export const fallbackTotal = new Counter({
  name: 'sfu_fallback_total',
  help: 'Срабатывания fallback-подмен по местам в коде',
  labelNames: ['site', 'expected'] as const,
});

/**
 * Режим читается на каждом вызове, а не при импорте: тесты и отладка меняют
 * окружение на ходу, а цена чтения переменной ничтожна на фоне того, что
 * происходит вокруг сработавшей подмены.
 */
export function fallbackMode(): FallbackMode {
  const explicit = (process.env.FALLBACK_MODE ?? '').trim();
  if (explicit === 'strict' || explicit === 'log') return explicit;
  return (process.env.HTQ_ENV ?? '').trim() === 'development' ? 'strict' : 'log';
}

export const isStrict = (): boolean => fallbackMode() === 'strict';

interface FallbackOptions {
  /** Человеческое объяснение — попадёт в лог и в текст исключения. */
  reason: string;
  /** Предусмотренная деградация: строгий режим её не роняет. */
  expected?: boolean;
  /** Исходная ошибка, если подмена случилась в `catch`. */
  cause?: unknown;
  /** Переменные детали для лога (в метрику НЕ идут). */
  context?: Record<string, unknown>;
}

/**
 * Зарегистрировать подмену и вернуть `value` (либо упасть в строгом режиме).
 *
 * `site` — СТАТИЧЕСКИЙ литерал вида `sfu.<модуль>.<что>`: он уходит в метку
 * метрики, поэтому подставлять туда данные нельзя. Переменная часть — в
 * `context`.
 */
export function fallback<T>(site: string, value: T, options: FallbackOptions): T {
  const { reason, expected = false, cause, context } = options;
  fallbackTotal.inc({ site, expected: expected ? 'true' : 'false' });

  const message = `FALLBACK site=${site} reason=${reason}`;

  if (!expected && fallbackMode() === 'strict') {
    throw new FallbackNotAllowed(
      `${message} | подмена запрещена: HTQ_ENV=development. Устраните причину, `
        + 'а если это предусмотренная деградация — передайте expected: true.',
      { cause }
    );
  }

  const log = expected ? console.info : console.warn;
  log(message, context ?? '', cause ?? '');
  return value;
}
