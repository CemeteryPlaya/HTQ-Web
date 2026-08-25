/**
 * Стаж сотрудника — «сколько уже работает», рядом с датой приёма.
 *
 * Считается календарно (годы/месяцы/дни), а не делением разницы в
 * миллисекундах: 29 февраля и месяцы разной длины иначе дают «11 месяцев»
 * там, где человек отработал ровно год.
 */
import type { TFunction } from 'i18next';

export interface TenureParts {
  years: number;
  months: number;
  days: number;
}

/** ``YYYY-MM-DD`` через ``new Date()`` разбирается как полночь UTC, и в
 * отрицательных таймзонах ``getDate()`` возвращает предыдущий день. Поэтому
 * ISO-дату собираем в локальную вручную. */
function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (iso) return new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Прибавить месяцы, прижимая день к последнему числу месяца (31 января + 1
 * месяц = 29/28 февраля, а не 2/3 марта). */
function addMonths(base: Date, count: number): Date {
  const month = base.getMonth() + count;
  const lastDay = new Date(base.getFullYear(), month + 1, 0).getDate();
  return new Date(base.getFullYear(), month, Math.min(base.getDate(), lastDay));
}

/**
 * Стаж от даты приёма до даты увольнения (если сотрудник уволен) или до
 * `now`. `null` — если даты приёма нет, она нечитаема или лежит в будущем.
 */
export function tenureParts(
  hireDate: string | null | undefined,
  endDate: string | null | undefined = null,
  now: Date = new Date(),
): TenureParts | null {
  const from = parseDate(hireDate);
  if (!from) return null;
  const to = parseDate(endDate) ?? now;
  if (to.getTime() < from.getTime()) return null;

  // Считаем через «якорь»: дата приёма, сдвинутая на N полных месяцев с
  // прижатием к концу месяца. Наивное вычитание полей ломается на приёме
  // 31-го числа (31 января → 1 марта дало бы отрицательные дни).
  let totalMonths =
    (to.getFullYear() - from.getFullYear()) * 12 + (to.getMonth() - from.getMonth());
  if (addMonths(from, totalMonths).getTime() > to.getTime()) totalMonths -= 1;
  const anchor = addMonths(from, totalMonths);
  const days = Math.round((to.getTime() - anchor.getTime()) / 86_400_000);
  const years = Math.floor(totalMonths / 12);
  const months = totalMonths % 12;
  return { years, months, days };
}

/**
 * Человекочитаемый стаж: максимум две единицы (годы+месяцы, иначе месяцы,
 * иначе дни) — «3 года 2 месяца» читается, «3 года 2 месяца 2 дня» уже нет.
 */
export function formatTenure(
  t: TFunction,
  hireDate: string | null | undefined,
  endDate: string | null | undefined = null,
  now: Date = new Date(),
): string | null {
  const parts = tenureParts(hireDate, endDate, now);
  if (!parts) return null;
  const { years, months, days } = parts;
  if (years > 0) {
    const head = t('hr.card.tenureYears', { count: years });
    return months > 0 ? `${head} ${t('hr.card.tenureMonths', { count: months })}` : head;
  }
  if (months > 0) return t('hr.card.tenureMonths', { count: months });
  return t('hr.card.tenureDays', { count: days });
}
