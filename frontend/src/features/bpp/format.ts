/**
 * Суммы и даты модуля БЗО (мастер-план §3): `1 250 000,00 KZT`, `ДД.ММ.ГГГГ`.
 *
 * Общий формат придёт с каркасом раздела `/bpp` (A2.1) — тогда эти функции
 * уступят ему место.
 */

const moneyFormat = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Разделитель разрядов у ru-RU — неразрывный пробел (U+00A0 или узкий
// U+202F, зависит от версии ICU); в документах модуля — обычный пробел.
const GROUP_SPACES = new RegExp(`[${String.fromCharCode(0xa0, 0x202f)}]`, 'g');

export const formatMoney = (value: string | number, currency?: string): string => {
  const text = moneyFormat.format(Number(value)).replace(GROUP_SPACES, ' ').replace('.', ',');
  return currency ? `${text} ${currency}` : text;
};

export const formatDate = (iso: string | null): string => {
  if (!iso) return '—';
  const [year, month, day] = iso.slice(0, 10).split('-');
  return `${day}.${month}.${year}`;
};
