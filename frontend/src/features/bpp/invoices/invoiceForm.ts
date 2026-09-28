/**
 * Состояние формы F-05 «Счёт на оплату» и её правила (ТЗ §10.2–10.3) —
 * отдельно от экрана, чтобы проверять без рендера.
 *
 * - По договору контрагент, валюта, НДС и тип — из договора (§10.3 п.2);
 *   «Без договора» они редактируемы.
 * - Порог 1000 МРП (BR-040) — у счёта без договора в тенге считается на
 *   лету; в валюте — по сумме в KZT с сервера (курс на дату счёта).
 * - Σ строк = сумме счёта (BR-044), количество ≤ остатка позиции (BR-042).
 */
import { fromCents, lessThan, sumMoney, toCents } from '../budgets/cents';
import { formatMoney, parseMoneyInput } from '../format';
import { shownQty } from '../plan/planSelection';
import { parseQtyInput } from '../requests/requestForm';

import type { CounterpartyBrief } from '../agreements/api';
import type { InvoiceCard, InvoicePatch } from './api';

export const COMMENT_MAX = 1000;

/** Сегодня по часам браузера, `ГГГГ-ММ-ДД` (не UTC: в Алматы утро — ещё вчера по UTC). */
export const localToday = (): string => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

export interface InvoiceFormState {
  counterparty: CounterpartyBrief | null;
  ext_number: string;
  ext_date: string;
  amount: string;
  currency_code: string;
  /** Фактический курс, как ввёл человек; `rate_manual` — курс правлен вручную. */
  rate: string;
  rate_manual: boolean;
  with_vat: boolean;
  vat_rate: string;
  vat_manual: boolean;
  purchase_type: 'goods' | 'works' | '';
  is_advance: boolean;
  due_date: string;
  author_comment: string;
  lines: { id: string; qty: string; amount: string }[];
}

export function formOf(card: InvoiceCard | undefined): InvoiceFormState {
  if (!card) {
    return {
      counterparty: null, ext_number: '', ext_date: '', amount: '', currency_code: 'KZT',
      rate: '', rate_manual: false, with_vat: true, vat_rate: '', vat_manual: false,
      purchase_type: '', is_advance: false, due_date: '', author_comment: '', lines: [],
    };
  }
  return {
    counterparty: card.counterparty,
    ext_number: card.ext_number,
    ext_date: card.ext_date ?? '',
    amount: formatMoney(card.amount),
    currency_code: card.currency_code,
    rate: card.rate ?? '',
    rate_manual: card.rate_source === 'manual',
    with_vat: card.with_vat,
    vat_rate: card.vat_rate ?? '',
    vat_manual: card.vat_source === 'manual',
    purchase_type: card.purchase_type,
    is_advance: card.is_advance,
    due_date: card.due_date ?? '',
    author_comment: card.author_comment,
    lines: card.lines.map((line) => ({
      id: line.id, qty: shownQty(line.qty), amount: formatMoney(line.amount),
    })),
  };
}

/** Тело PATCH. По договору реквизиты договора не отправляются вовсе. */
export function patchOf(form: InvoiceFormState, card: InvoiceCard): InvoicePatch {
  const byContract = card.basis === 'contract';
  const patch: InvoicePatch = {
    ext_number: form.ext_number.trim(),
    ext_date: form.ext_date || null,
    amount: parseMoneyInput(form.amount) ?? '0.00',
    is_advance: form.is_advance,
    due_date: form.due_date || null,
    author_comment: form.author_comment.trim(),
    lines: form.lines.map((line) => ({
      id: line.id,
      qty: parseQtyInput(line.qty) ?? '0',
      amount: parseMoneyInput(line.amount) ?? '0.00',
    })),
  };
  if (!byContract) {
    patch.counterparty_id = form.counterparty?.id ?? null;
    patch.currency_code = form.currency_code;
    patch.with_vat = form.with_vat;
    if (form.purchase_type) patch.purchase_type = form.purchase_type;
    if (form.vat_manual) patch.vat_rate = form.vat_rate.replace(',', '.') || null;
    else if (card.vat_source === 'manual') patch.vat_rate = null;
  }
  if (form.rate_manual) patch.rate = form.rate.replace(',', '.') || null;
  else if (card.rate_source === 'manual') patch.rate = null;
  return patch;
}

const milli = (value: string): bigint => BigInt((parseQtyInput(value) ?? '0').replace('.', ''));

/** Ошибки перед «Отправить ФД»: ключ — поле или `line:<id>`. */
export function submitErrors(form: InvoiceFormState, card: InvoiceCard, today: string
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.counterparty) errors.counterparty = 'Выберите контрагента';
  else if (form.counterparty.status !== 'active') errors.counterparty = 'Контрагент не активен';
  if (!form.ext_number.trim()) errors.ext_number = 'Укажите номер счёта контрагента';
  if (!form.ext_date) errors.ext_date = 'Укажите дату счёта';
  else if (form.ext_date > today) errors.ext_date = 'Дата счёта — не позже сегодняшней';
  if (form.due_date && form.ext_date && form.due_date < form.ext_date) {
    errors.due_date = 'Срок оплаты — не раньше даты счёта';
  }
  if (!form.purchase_type) errors.purchase_type = 'Выберите тип приобретения';
  const amount = parseMoneyInput(form.amount);
  if (amount === null || lessThan(amount, '0.01')) errors.amount = 'Сумма счёта — больше нуля';
  if (form.lines.length === 0) errors.lines = 'В счёте нужна хотя бы одна строка';
  const byId = new Map(card.lines.map((line) => [line.id, line]));
  for (const line of form.lines) {
    const qty = parseQtyInput(line.qty);
    const available = byId.get(line.id)?.qty_available ?? '0';
    const lineAmount = parseMoneyInput(line.amount);
    if (qty === null || BigInt(qty.replace('.', '')) <= 0n) {
      errors[`line:${line.id}`] = 'Количество — больше нуля';
    } else if (BigInt(qty.replace('.', '')) > milli(available)) {
      errors[`line:${line.id}`] = `Не больше остатка ${shownQty(available)}`;
    } else if (lineAmount === null || lessThan(lineAmount, '0.01')) {
      errors[`line:${line.id}`] = 'Сумма строки — больше нуля';
    }
  }
  if (amount !== null) {
    const total = sumMoney(form.lines.map((line) => parseMoneyInput(line.amount)));
    if (total !== amount) {
      errors.lines_total = `Сумма строк ${formatMoney(total)} не равна сумме счёта ${formatMoney(amount)}`;
    }
  }
  return errors;
}

/** Сумма в KZT по курсу: `amount × rate`, до тиына «половина — вверх» (как сервер). */
export function toKzt(amount: string, rate: string): string | null {
  const cents = toCents(amount);
  const match = /^(\d+)(?:\.(\d{1,6}))?$/.exec(rate.trim().replace(',', '.'));
  if (cents === null || cents < 0n || !match) return null;
  const micro = BigInt(match[1] + (match[2] ?? '').padEnd(6, '0'));
  return fromCents((cents * micro + 500_000n) / 1_000_000n);
}

/**
 * Превышение порога 1000 МРП (BR-040) у счёта без договора: `threshold` —
 * порог на дату счёта с сервера. В тенге сравнивается введённая сумма, в
 * валюте — она же по курсу (ручному или НБРК из карточки). `null` — порог
 * не применим или посчитать нечем: решит сервер при отправке.
 */
export function overThreshold(form: InvoiceFormState, card: InvoiceCard,
  threshold: string | null): boolean | null {
  if (card.basis !== 'no_contract' || !threshold) return null;
  const amount = parseMoneyInput(form.amount);
  if (amount === null) return null;
  if (form.currency_code === 'KZT') return lessThan(threshold, amount);
  const rate = form.rate_manual ? form.rate
    : form.currency_code === card.currency_code ? card.rate : null;
  const kzt = rate ? toKzt(amount, rate) : null;
  return kzt === null ? null : lessThan(threshold, kzt);
}
