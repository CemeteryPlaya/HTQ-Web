/**
 * Расчёты формы F-07 «на лету» в целых тиынах и масштабированных количествах
 * (`bigint`), без `float` (CALC-013, ТЗ §12.3). Окончательные числа считает
 * сервер при сохранении (округление — `ROUND_HALF_UP`, как здесь); экран
 * показывает то же самое до сохранения.
 *
 * Знак отклонения — как у сервера (`deviation_pct`): плюс — АП ДОРОЖЕ
 * исходного, минус — дешевле. Экономия — наоборот: плюс — дешевле. Поэтому
 * отклонение и экономия по знаку не пересчитываются друг из друга.
 */
import { fromCents, toCents } from '../bank/amounts';

const QTY = /^(\d+)(?:\.(\d+))?$/;

/** Количество «10.500» → {units: 10500n, scale: 3}; не число — `null`. */
export function parseQty(text: string): { units: bigint; scale: number } | null {
  const match = QTY.exec(text.trim());
  if (!match) return null;
  const frac = match[2] ?? '';
  return { units: BigInt(match[1] + frac), scale: frac.length };
}

/** Деление с округлением half-up по модулю (как `Decimal.quantize(ROUND_HALF_UP)`). */
export function divRound(numerator: bigint, denominator: bigint): bigint {
  const negative = (numerator < 0n) !== (denominator < 0n);
  const n = numerator < 0n ? -numerator : numerator;
  const d = denominator < 0n ? -denominator : denominator;
  const quotient = (2n * n + d) / (2n * d);
  return negative ? -quotient : quotient;
}

/** Сумма строки, тиыны: кол-во × цена за единицу (цена — тиыны), округление до тиына. */
export function lineCents(qty: string, priceCents: bigint): bigint | null {
  const parsed = parseQty(qty);
  if (!parsed) return null;
  return divRound(parsed.units * priceCents, 10n ** BigInt(parsed.scale));
}

/** Строка-десятичная цены исходной позиции («1234.56») → тиыны. */
export const priceCents = (price: string): bigint | null => toCents(price);

/** Сотые доли процента → «12,50» (запятая, как в модуле). */
export function formatPct(hundredths: bigint): string {
  const negative = hundredths < 0n;
  const abs = negative ? -hundredths : hundredths;
  return `${negative ? '-' : ''}${abs / 100n},${(abs % 100n).toString().padStart(2, '0')}`;
}

/** Отклонение цены АП от исходной, % в сотых долях: (цена − исходная) / исходная. */
export function deviationHundredths(price: bigint, sourcePrice: bigint): bigint | null {
  if (sourcePrice === 0n) return null;
  return divRound((price - sourcePrice) * 10000n, sourcePrice);
}

export interface Saving {
  /** Исходная часть − сумма АП, тиыны; отрицательная — удорожание. */
  amount: bigint;
  /** Процент от исходной части, сотые доли; нулевая часть — 0. */
  pct: bigint;
  moreExpensive: boolean;
}

/** CALC-013: экономия и её процент от исходной части. */
export function saving(sourceCents: bigint, offerCents: bigint): Saving {
  const amount = sourceCents - offerCents;
  return {
    amount,
    pct: sourceCents === 0n ? 0n : divRound(amount * 10000n, sourceCents),
    moreExpensive: amount < 0n,
  };
}

/** Экономия по строкам сервера (`amount`, `pct` — «12.50») → `Saving`; не числа — `null`. */
export function savingFromString(amount: string, pct: string): Saving | null {
  const amountCents = toCents(amount);
  const pctHundredths = toCents(pct);
  if (amountCents === null || pctHundredths === null) return null;
  return { amount: amountCents, pct: pctHundredths, moreExpensive: amountCents < 0n };
}

/** Тиыны → «1250000.00» (для `formatMoney`; валюту добавляет вызывающий). */
export const centsToDecimal = fromCents;
