/**
 * Деньги сверки в целых тиынах (`bigint`): распределение платежа по счетам
 * считается точно, без `float` (Decimal(18,2) не помещается в `number`).
 * Строки-десятичные приходят с сервера как `"1250000.00"`; ввод человека
 * нормализует `parseMoneyInput`.
 */
import { parseMoneyInput } from '../format';

const DECIMAL = /^(-?)(\d+)(?:\.(\d{1,2}))?$/;

/** `"1250.5"` → `125050n`; не десятичное — `null`. */
export function toCents(value: string): bigint | null {
  const match = DECIMAL.exec(value.trim());
  if (!match) return null;
  const [, sign, whole, frac = ''] = match;
  const cents = BigInt(whole) * 100n + BigInt(frac.padEnd(2, '0'));
  return sign ? -cents : cents;
}

/** `125050n` → `"1250.50"`. */
export function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const frac = (abs % 100n).toString().padStart(2, '0');
  return `${negative ? '-' : ''}${abs / 100n}.${frac}`;
}

/** Ввод человека («1 250,50») → тиыны; непонятное — `null`. */
export function centsFromInput(text: string): bigint | null {
  const normalized = parseMoneyInput(text);
  return normalized === null ? null : toCents(normalized);
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Куски назначения: найденные номера счетов помечены. Номер ищется
 * терпимо к разделителям — `СЧ-2026-000123` находит и «сч 2026 000123»,
 * так же его находит сервер (ТЗ §11.3).
 */
export function splitPurpose(purpose: string, numbers: string[]): { text: string; hit: boolean }[] {
  const patterns = numbers
    .map((number) => number.split(/[^0-9A-Za-zА-Яа-яЁё]+/).filter(Boolean).map(escape))
    .filter((tokens) => tokens.length > 0)
    .map((tokens) => tokens.join('[\\s_./№-]*'));
  if (patterns.length === 0 || !purpose) return [{ text: purpose, hit: false }];
  const regex = new RegExp(`(${patterns.join('|')})`, 'giu');
  const parts: { text: string; hit: boolean }[] = [];
  let last = 0;
  for (const match of purpose.matchAll(regex)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: purpose.slice(last, start), hit: false });
    parts.push({ text: match[0], hit: true });
    last = start + match[0].length;
  }
  if (last < purpose.length) parts.push({ text: purpose.slice(last), hit: false });
  return parts.length > 0 ? parts : [{ text: purpose, hit: false }];
}
