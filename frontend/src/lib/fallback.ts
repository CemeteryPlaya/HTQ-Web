/**
 * lib/fallback.ts
 *
 * Подмена значения, которую слышно. Зеркало backend'ного `htqweb/fallback.py`
 * — те же понятия, тот же формат строки, та же ось среды, чтобы «подменилось
 * на фронте» и «подменилось на бэке» читались одинаково.
 *
 * Два режима, ось — `VITE_HTQ_ENV`:
 *
 * - `production` / `staging` — подмена происходит, пользователь ничего не
 *   замечает (в разметке не появляется ни баннера, ни пометки), но в консоль
 *   уходит строка `FALLBACK …`, а событие — в телеметрию, откуда попадает в
 *   Loki рядом с серверными;
 * - `development` — подмены НЕТ: летит `FallbackNotAllowedError`, React
 *   показывает красный оверлей Vite. Разработчик видит причину, а не её
 *   замаскированное следствие.
 *
 * `expected: true` — предусмотренная деградация, у которой нет «настоящей
 * причины»: камеры может не быть, доступа к домену может не быть. Строгий
 * режим её не роняет (иначе разработчик без веб-камеры не смог бы зайти в
 * конференцию) и в консоль она идёт уровнем debug — но в телеметрию уходит
 * наравне с остальными: всплеск «у всех пропали камеры» видеть надо.
 *
 * Что сюда НЕ заворачивается — и это важнее списка того, что заворачивается:
 *
 * - чисто визуальные заглушки (`|| '—'`, `key`, дефолтный текст ошибки) —
 *   там не подменяются данные, только вид пустоты;
 * - подстановки состояния загрузки (`data?.items ?? []`) — они срабатывают в
 *   каждом рендере, и метка FALLBACK на них обесценила бы все остальные.
 */
import { logUserAction } from '@/lib/telemetry';

export class FallbackNotAllowedError extends Error {
  /** Исходная ошибка, из-за которой сработала подмена.
   *
   *  Поле объявлено и присваивается вручную, а не передаётся вторым
   *  аргументом `Error(msg, { cause })`: в браузерах это работает, но `lib`
   *  проекта ниже ES2022, и типы такой конструктор не знают. Поведение
   *  идентичное, зато сборка не зависит от версии библиотеки типов. */
  readonly cause?: unknown;

  constructor(message: string, options?: { cause?: unknown }) {
    super(message);
    this.name = 'FallbackNotAllowedError';
    this.cause = options?.cause;
  }
}

export type FallbackMode = 'log' | 'strict';

interface FallbackOptions {
  /** Человеческое объяснение — попадёт в консоль и в текст исключения. */
  reason: string;
  /** Штатная деградация: строгий режим её не роняет. */
  expected?: boolean;
  /** Исходная ошибка, если подмена случилась в `catch`. */
  cause?: unknown;
  /** Переменные детали для консоли (в телеметрию идут как meta). */
  context?: Record<string, unknown>;
}

/**
 * Режим читается на каждом вызове, а не один раз при импорте: тесты
 * подменяют окружение через `vi.stubEnv`, а цена чтения поля ничтожна на
 * фоне того, что происходит вокруг сработавшей подмены.
 *
 * Без явной `VITE_HTQ_ENV` среда берётся из режима сборки Vite. Это не
 * подмена в смысле этого модуля, а обычный дефолт конфигурации: `DEV` знает
 * ровно то же самое — собрано для разработчика или нет.
 */
export function fallbackMode(): FallbackMode {
  // Явный режим перебивает среду — тем же правилом и по той же причине, что
  // FALLBACK_MODE на бэкенде: включить строгий режим на стейдже или разово
  // ослабить его локально, когда чинишь что-то другое.
  const explicit = import.meta.env.VITE_FALLBACK_MODE;
  if (explicit === 'strict' || explicit === 'log') return explicit;

  const env = import.meta.env.VITE_HTQ_ENV
    ?? (import.meta.env.DEV ? 'development' : 'production');
  return env === 'development' ? 'strict' : 'log';
}

export const isStrict = (): boolean => fallbackMode() === 'strict';

// Троттлинг отправки: не чаще одной телеметрии на site в минуту. Без него
// подмена внутри рендера отправила бы сотню запросов на первом же кадре.
const THROTTLE_MS = 60_000;
const lastSent = new Map<string, number>();

function shouldSend(site: string): boolean {
  const now = Date.now();
  const previous = lastSent.get(site);
  if (previous !== undefined && now - previous < THROTTLE_MS) return false;
  lastSent.set(site, now);
  return true;
}

/** Только для тестов: сбросить окно троттлинга. */
export function resetFallbackThrottle(): void {
  lastSent.clear();
}

/**
 * Зарегистрировать подмену и вернуть `value` (либо упасть в строгом режиме).
 *
 * `site` — СТАТИЧЕСКИЙ литерал вида `<область>.<файл>.<что>`; он уходит в
 * метку события, поэтому подставлять туда данные нельзя. Переменная часть —
 * в `context`.
 */
export function fallback<T>(site: string, value: T, options: FallbackOptions): T {
  const { reason, expected = false, cause, context } = options;
  const message = `FALLBACK site=${site} reason=${reason}`;

  if (!expected && fallbackMode() === 'strict') {
    throw new FallbackNotAllowedError(
      `${message} | подмена запрещена: VITE_HTQ_ENV=development. Устраните `
      + `причину, а если это штатная деградация — передайте expected: true.`,
      { cause },
    );
  }

  // debug против warn: предусмотренная деградация не должна шуметь наравне
  // со сбоем, иначе на предупреждения перестанут смотреть.
  const log = expected ? console.debug : console.warn;
  log(message, { ...context, cause });

  if (shouldSend(site)) {
    logUserAction({
      action: 'fallback',
      resource: site,
      meta: { reason, expected, ...context },
    });
  }
  return value;
}
