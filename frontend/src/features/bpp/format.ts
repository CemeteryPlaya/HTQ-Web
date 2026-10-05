/**
 * Суммы и даты модуля БЗО (ТЗ §05, §13.2; мастер-план §3):
 * `1 250 000,00 KZT`, `ДД.ММ.ГГГГ`, `ДД.ММ.ГГГГ ЧЧ:ММ` по Asia/Almaty.
 *
 * Суммы приходят с сервера строками-десятичными (`Decimal(18,2)`), и здесь
 * они НЕ проходят через `float`: `Number("99999999999999.99")` уже теряет
 * последний разряд, а в денежном документе это другая сумма. Поэтому
 * `formatMoney` разбирает строку сама, а округление до копейки — то же, что
 * на сервере (`apps/bpp/services/money.py`, `ROUND_HALF_UP`), — делает на
 * `BigInt`.
 */

// Разделители, которые человек может вставить из Excel или из нашего же
// формата: обычный пробел, неразрывный (U+00A0) и узкий неразрывный (U+202F).
const INPUT_SPACES = new RegExp(`[\\s${String.fromCharCode(0xa0, 0x202f)}]`, 'g');

const DECIMAL = /^([+-])?(\d*)(?:\.(\d*))?$/;

/** Разряды целой части через обычный пробел: `1250000` → `1 250 000`. */
const groupThousands = (digits: string): string =>
  digits.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

/**
 * Строка-десятичная → `[знак, целая часть, две цифры копеек]` с округлением
 * half-up по модулю (как `Decimal.quantize(ROUND_HALF_UP)`). `null` — не число.
 */
function toCents(text: string): [boolean, string, string] | null {
  const match = DECIMAL.exec(text);
  if (!match) return null;
  const [, sign, intPart = '', fracPart = ''] = match;
  if (!intPart && !fracPart) return null;

  const cents = BigInt((intPart || '0') + fracPart.padEnd(2, '0').slice(0, 2));
  const roundUp = fracPart.length > 2 && fracPart[2] >= '5';
  const total = (cents + (roundUp ? 1n : 0n)).toString().padStart(3, '0');

  const whole = total.slice(0, -2).replace(/^0+(?=\d)/, '');
  const fraction = total.slice(-2);
  // «-0,00» не бывает: ноль без знака.
  const negative = sign === '-' && /[1-9]/.test(total);
  return [negative, whole, fraction];
}

/**
 * Сумма в формате модуля: `"1250000.5"` → `"1 250 000,50"`, с валютой —
 * `"1 250 000,50 KZT"`.
 *
 * Число (не строка) переводится через `String` — без арифметики над ним.
 * Нераспознанное значение возвращается как есть: выдумать сумму хуже, чем
 * показать то, что прислали.
 */
export const formatMoney = (value: string | number, currency?: string): string => {
  const raw = String(value).trim();
  const parts = toCents(raw);
  const text = parts
    ? `${parts[0] ? '-' : ''}${groupThousands(parts[1])},${parts[2]}`
    : raw;
  return currency ? `${text} ${currency}` : text;
};

export const formatDate = (iso: string | null): string => {
  if (!iso) return '—';
  const [year, month, day] = iso.slice(0, 10).split('-');
  return `${day}.${month}.${year}`;
};

// Один экземпляр на модуль: конструктор `Intl.DateTimeFormat` дорогой, а
// реестр на 100 строк звал бы его на каждую ячейку.
const almatyDateTime = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Almaty',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/**
 * Момент времени в формате модуля — `ДД.ММ.ГГГГ ЧЧ:ММ` по Asia/Almaty,
 * независимо от часового пояса браузера: `2026-09-27T20:30:00Z` →
 * `28.09.2026 01:30`. Собирается из `formatToParts`, а не из готовой строки
 * `ru-RU`: её разделитель («, » или « ») зависит от версии ICU.
 */
export const formatDateTime = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return '—';
  const part: Record<string, string> = {};
  for (const { type, value } of almatyDateTime.formatToParts(moment)) part[type] = value;
  return `${part.day}.${part.month}.${part.year} ${part.hour}:${part.minute}`;
};

/**
 * Ввод суммы человеком → строка-десятичная для сервера (ТЗ §13.2 «Числовой
 * формат»): `"1 250 000,00"` → `"1250000.00"`.
 *
 * Пробелы любых видов отбрасываются, разделитель дробной части — запятая или
 * точка (одна). Больше двух знаков после запятой или не число — `null`:
 * такой ввод форма не принимает («Введите сумму в формате 1 250 000,00»),
 * а не округляет молча. Положительность — отдельная проверка формы.
 */
export const parseMoneyInput = (text: string): string | null => {
  const compact = text.replace(INPUT_SPACES, '').replace(',', '.');
  const match = DECIMAL.exec(compact);
  if (!match) return null;
  const [, sign, intPart = '', fracPart = ''] = match;
  if (!intPart && !fracPart) return null;
  if (fracPart.length > 2) return null;
  const whole = (intPart || '0').replace(/^0+(?=\d)/, '');
  const cents = fracPart.padEnd(2, '0');
  const negative = sign === '-' && /[1-9]/.test(whole + cents);
  return `${negative ? '-' : ''}${whole}.${cents}`;
};
