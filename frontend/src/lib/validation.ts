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
