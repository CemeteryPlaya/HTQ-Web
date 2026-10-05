/**
 * Десятичные значения справочников, у которых знаков после запятой не два:
 * курс валюты — `Decimal(18,6)`, ставка НДС — `Decimal(5,2)` в процентах.
 *
 * `formatMoney`/`parseMoneyInput` из `../format` жёстко округляют до копейки
 * и для курса не годятся (`475,123456` превратился бы в `475,12`). Правило то
 * же, что у денег: значение живёт строкой и через `float` не проходит —
 * `Number("475.123456")` безопасен, но `Number` у восемнадцатизначного
 * значения — уже нет, и лучше не держать двух правил.
 */

// Те же разделители, что принимает `parseMoneyInput`: обычный пробел,
// неразрывный (U+00A0) и узкий неразрывный (U+202F).
const INPUT_SPACES = new RegExp(`[\\s${String.fromCharCode(0xa0, 0x202f)}]`, 'g');

const DECIMAL = /^([+-])?(\d*)(?:\.(\d*))?$/;

const groupThousands = (digits: string): string =>
  digits.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

/**
 * Строка-десятичная с сервера → показ: `"475.120000"` → `"475,12"`.
 *
 * Хвостовые нули дробной части отбрасываются, но не ниже `minPlaces` знаков
 * (курс `475,12`, а не `475,120000`; ставка `12,00`). Нераспознанное
 * значение возвращается как есть — выдумывать число хуже, чем показать
 * присланное.
 */
export function formatDecimal(value: string | null | undefined, minPlaces = 2): string {
  if (value === null || value === undefined || value === '') return '—';
  const match = DECIMAL.exec(String(value).trim());
  if (!match) return String(value);
  const [, sign = '', intPart = '', fracPart = ''] = match;
  if (!intPart && !fracPart) return String(value);
  let fraction = fracPart.replace(/0+$/, '');
  if (fraction.length < minPlaces) fraction = fraction.padEnd(minPlaces, '0');
  const whole = groupThousands((intPart || '0').replace(/^0+(?=\d)/, ''));
  const negative = sign === '-' && /[1-9]/.test(intPart + fracPart);
  return `${negative ? '-' : ''}${whole}${fraction ? `,${fraction}` : ''}`;
}

/**
 * Ввод человека → строка-десятичная для сервера: `"1 475,5"` → `"1475.5"`.
 *
 * Пробелы любых видов отбрасываются, дробная часть — через запятую или
 * точку. Знаков после запятой больше `maxPlaces`, знак минус или не число —
 * `null`: форма такой ввод не принимает, а не округляет молча (тот же
 * принцип, что у `parseMoneyInput`). Больше ли нуля — отдельная проверка.
 */
export function parseDecimalInput(text: string, maxPlaces: number): string | null {
  const compact = text.replace(INPUT_SPACES, '').replace(',', '.');
  const match = DECIMAL.exec(compact);
  if (!match) return null;
  const [, sign, intPart = '', fracPart = ''] = match;
  if (sign === '-') return null;
  if (!intPart && !fracPart) return null;
  if (fracPart.length > maxPlaces) return null;
  const whole = (intPart || '0').replace(/^0+(?=\d)/, '');
  return fracPart ? `${whole}.${fracPart}` : whole;
}

/** Строго больше нуля — по цифрам, без перевода в число. */
export const isPositiveDecimal = (value: string): boolean => /[1-9]/.test(value);

/**
 * Не больше ли `value` порога `limit` — для процента НДС (0…100). Сравнение
 * по целой части достаточно: дробь у порога нулевая.
 */
export function notAboveWhole(value: string, limit: number): boolean {
  const [whole, fraction = ''] = value.split('.');
  const wholeNumber = Number(whole);
  if (wholeNumber < limit) return true;
  return wholeNumber === limit && !/[1-9]/.test(fraction);
}

/** `"4325.00"` → `"4325000.00"`: умножение на 1000 сдвигом запятой. */
export function thousandTimes(value: string): string {
  const [whole, fraction = ''] = value.split('.');
  const padded = fraction.padEnd(3, '0');
  const shifted = `${whole}${padded.slice(0, 3)}`.replace(/^(-?)0+(?=\d)/, '$1');
  const rest = padded.slice(3);
  return rest ? `${shifted}.${rest}` : shifted;
}
