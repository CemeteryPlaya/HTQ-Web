/**
 * Арифметика денег на фронте — в копейках `BigInt`, без `float` (ТЗ §13.2):
 * итоги формы бюджета и заявки пересчитываются на лету, а `0.1 + 0.2` в
 * сумме лимитов недопустимо. Вход и выход — строки-десятичные сервера
 * (`"1250000.00"`, как отдаёт `parseMoneyInput`).
 */

const DECIMAL = /^(-)?(\d*)(?:\.(\d*))?$/;

/** `"1250000.5"` → `125000050n`; не число — `null`. Больше двух знаков — отбрасываются. */
export function toCents(value: string | number | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  const match = DECIMAL.exec(String(value).trim());
  if (!match) return null;
  const [, sign, whole = '', frac = ''] = match;
  if (!whole && !frac) return null;
  const cents = BigInt(whole || '0') * 100n + BigInt((frac + '00').slice(0, 2));
  return sign ? -cents : cents;
}

/** `125000050n` → `"1250000.50"`. */
export function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, '0');
  return `${negative ? '-' : ''}${whole}.${frac}`;
}

/** Сумма строк-десятичных; нечисловые пропускаются. */
export function sumMoney(values: (string | number | null | undefined)[]): string {
  let total = 0n;
  for (const value of values) total += toCents(value) ?? 0n;
  return fromCents(total);
}

/** `a − b` строками-десятичными. */
export function subMoney(a: string | number, b: string | number): string {
  return fromCents((toCents(a) ?? 0n) - (toCents(b) ?? 0n));
}

/** `a < b` для строк-десятичных. */
export function lessThan(a: string | number, b: string | number): boolean {
  return (toCents(a) ?? 0n) < (toCents(b) ?? 0n);
}
