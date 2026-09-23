/**
 * Правила ввода, которые форма проверяет ДО отправки.
 *
 * Смысл не в том, чтобы продублировать сервер, а в том, чтобы человек узнал
 * об ошибке там, где он её делает — в поле, а не после «Сохранить». Поэтому
 * здесь только те правила, ответ на которые форме уже известен: порядок дат,
 * остаток по договору, формат суммы. Всё, что требует знания чужих строк
 * (занят ли номер, хватает ли прав), проверяет сервер, а его ответ показывает
 * `reportApiError` из `lib/apiError.ts`.
 *
 * Функции чистые и без React: их зовут из `validate()` конкретной формы —
 * приём, заведённый в `pages/contracts/InvoiceCreate.tsx`. Общий тут не
 * компонент, а формулировка: одно правило — один текст, иначе две формы
 * объясняют одно и то же разными словами.
 */

/** Текст отказа совпадает с формулировкой бэкенда (`htqweb/date_rules.py`). */
export const DATES_OUT_OF_ORDER = 'Дата начала позже даты окончания';

/**
 * Набрано что-то, из чего даты не выходит: «31.02.2026», «01.13.2026».
 *
 * Отдельно от «дат перепутали местами»: там обе даты существуют, а тут
 * неверна сама дата, и исправлять человеку надо разное.
 */
export const INVALID_DATE = 'Такой даты нет — проверьте день, месяц и год';

/**
 * Даты перепутаны местами.
 *
 * Пустая дата — не ошибка: обе даты необязательны почти везде, и «начало без
 * окончания» законно. Сравниваем строки `YYYY-MM-DD` из `<input type="date">`
 * напрямую: в этом формате лексикографический порядок совпадает с
 * хронологическим, и `new Date()` с его часовыми поясами не нужен.
 */
export function datesOutOfOrder(
  start: string | null | undefined,
  end: string | null | undefined,
): boolean {
  if (!start || !end) return false;
  return start > end;
}

/** Сегодняшняя дата `YYYY-MM-DD` по часам браузера (не UTC: иначе вечером
 *  в Алматы «сегодня» было бы уже завтра). */
export function todayIso(offsetDays = 0): string {
  const day = new Date();
  day.setDate(day.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** Границы «Даты договора» (ТЗ 9.2) — те же, что проверяет бэкенд
 *  (`CONTRACT_DATE_MIN` / `CONTRACT_DATE_AHEAD` в `apps/contracts/schemas.py`). */
export const CONTRACT_DATE_MIN = '2020-01-01';
export const CONTRACT_DATE_AHEAD_DAYS = 30;

/** Текст совпадает с бэкендом (`htqweb/date_rules.py`). */
export const VALID_UNTIL_BEFORE_DATE = 'Срок действия договора раньше даты договора';

/** Что не так с датой договора; `null` — всё в порядке. Пустая — ошибка:
 *  дата обязательна, по ней проверяется уникальность договора. */
export function contractDateProblem(value: string | null | undefined): string | null {
  if (!value) return 'Укажите дату договора';
  if (value < CONTRACT_DATE_MIN) return 'Дата договора не может быть раньше 01.01.2020';
  const latest = todayIso(CONTRACT_DATE_AHEAD_DAYS);
  if (value > latest) {
    const [y, m, d] = latest.split('-');
    return `Дата договора не может быть позже ${d}.${m}.${y} (сегодня + ${CONTRACT_DATE_AHEAD_DAYS} дней)`;
  }
  return null;
}

/** Сумма из поля ввода: запятая и точка равноправны, пусто — `null`. */
export function parseAmount(raw: string | null | undefined): number | null {
  const text = (raw ?? '').trim().replace(',', '.');
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** Число с не более чем двумя знаками после запятой и больше нуля. */
export function invalidAmount(raw: string | null | undefined): boolean {
  const text = (raw ?? '').trim();
  if (!/^\d+([.,]\d{1,2})?$/.test(text)) return true;
  const value = parseAmount(text);
  return value === null || value <= 0;
}

/**
 * Сумма больше доступного остатка.
 *
 * Лимит приходит с сервера строкой (`Decimal` в JSON), поэтому принимаем и
 * строку, и число. Неизвестный лимит — не повод запрещать: пока остаток не
 * загружен, форма не должна мешать работать, а сервер всё равно проверит.
 */
export function overLimit(
  raw: string | null | undefined,
  limit: string | number | null | undefined,
): boolean {
  const value = parseAmount(raw);
  const cap = typeof limit === 'number' ? limit : parseAmount(limit);
  if (value === null || cap === null) return false;
  return value > cap;
}

/**
 * Похожее имя уже есть в списке.
 *
 * Мягкое правило: возвращает подсказку, а не запрет. Дубли бывают законными
 * («Блок I» есть и на Сазагане, и на Алге), и запрет по догадке хуже ошибки —
 * человек не сможет сделать то, что вправе. Сравнение без регистра и лишних
 * пробелов: именно так дубль и появляется — «Алга» против «алга ».
 */
export function findSimilarName(
  name: string | null | undefined,
  existing: readonly string[],
): string | null {
  const needle = (name ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
  if (!needle) return null;
  return existing.find(
    (item) => item.trim().toLowerCase().replace(/\s+/g, ' ') === needle,
  ) ?? null;
}
