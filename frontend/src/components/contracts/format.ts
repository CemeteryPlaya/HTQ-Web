/**
 * Форматирование значений домена «Договоры» — отдельно от компонентов,
 * чтобы не ломать fast refresh (ср. `components/signoff/format.ts`).
 *
 * Суммы приходят СТРОКАМИ (Decimal(18,2) на бэкенде) и строками же здесь и
 * остаются: прогон через `Number` терял бы копейки на суммах договоров, а
 * `Intl.NumberFormat` принимает только number. Поэтому разряды разбиваются
 * регуляркой по целой части, а дробная переносится как есть.
 */

import i18next from '@/i18n';

/** `5000000.00` → `«5 000 000,00»`. */
export function formatAmount(value: string): string {
  const [whole, fraction = '00'] = value.split('.');
  const spaced = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${spaced},${fraction}`;
}

/** Сумма с валютой — то, что показывается в карточке. */
export function formatMoney(value: string, currency: string): string {
  return `${formatAmount(value)} ${currency}`;
}

/** ISO-дата (без времени) → «12.03.2026». Прочерк, если даты нет. */
export function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(i18next.language, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

/** ISO-момент → «12.03.2026, 14:05». Прочерк, если момента нет. */
export function formatMoment(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(i18next.language, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Цвет остатка бюджетной строки: красный при нуле и ниже, янтарный ниже
 * 15% от выделенного.
 *
 * ЗДЕСЬ прогон через `Number` допустим и точность не важна — считается не
 * сумма, а доля, и решается ей единственный вопрос «каким цветом красить».
 * Само число всегда показывается строкой через `formatAmount`.
 */
export function remainingTone(remaining: string, allocated: string): string {
  const left = Number(remaining);
  const total = Number(allocated);
  if (!Number.isFinite(left) || !Number.isFinite(total) || total === 0) return '';
  if (left <= 0) return 'text-destructive font-medium';
  if (left / total < 0.15) return 'text-amber-600 dark:text-amber-500 font-medium';
  return '';
}
