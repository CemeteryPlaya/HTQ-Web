/**
 * Состояние формы F-04 «Договор» и её правила (ТЗ §9.2–9.3) — отдельно от
 * экрана, чтобы проверять без рендера.
 *
 * - «Открытый договор» скрывает и очищает суммы (§9.3 п.2);
 * - «С НДС» снят — ставки нет (§9.3 п.3); ставку можно поправить вручную
 *   (D-14), «вернуть справочную» — снова ставка страны на дату;
 * - превышение над планом позиций — предупреждение с остатком статьи, больше
 *   остатка — отправка закрыта (§9.3 п.5, BR-034);
 * - Σ позиций = сумме у закрытого договора (BR-033), количество ≤ остатка
 *   позиции (BR-042).
 */
import { lessThan, subMoney, sumMoney } from '../budgets/cents';
import { formatMoney, parseMoneyInput } from '../format';
import { parseQtyInput } from '../requests/requestForm';

import type { AgreementCard, AgreementPatch, AgreementType, CounterpartyBrief } from './api';
import type { HistoryFieldOptions } from '../core/HistoryTab';

export const NAME_MIN = 3;

export interface AgreementFormState {
  counterparty: CounterpartyBrief | null;
  name: string;
  ext_number: string;
  ext_date: string;
  agreement_type: AgreementType;
  is_open: boolean;
  amount: string;
  with_vat: boolean;
  /** Ставка, как её ввёл человек; `vat_manual` — ставка правлена вручную. */
  vat_rate: string;
  vat_manual: boolean;
  valid_to: string;
  items: { id: string; qty: string; amount: string }[];
}

const qtyText = (value: string) =>
  (value.includes('.') ? value.replace(/\.?0+$/, '') : value).replace('.', ',');

/** Количество в тысячных (`"2.500"` → 2500n) — сравнение без `float`. */
const milli = (value: string): bigint => BigInt((parseQtyInput(value) ?? '0').replace('.', ''));

export function formOf(card: AgreementCard | undefined): AgreementFormState {
  if (!card) {
    return {
      counterparty: null, name: '', ext_number: '', ext_date: '', agreement_type: '',
      is_open: false, amount: '', with_vat: true, vat_rate: '', vat_manual: false,
      valid_to: '', items: [],
    };
  }
  return {
    counterparty: card.counterparty,
    name: card.name,
    ext_number: card.ext_number,
    ext_date: card.ext_date ?? '',
    agreement_type: card.agreement_type,
    is_open: card.is_open,
    amount: card.amount === null ? '' : formatMoney(card.amount),
    with_vat: card.with_vat,
    vat_rate: card.vat_rate ?? '',
    vat_manual: card.vat_source === 'manual',
    valid_to: card.valid_to ?? '',
    items: card.items.map((item) => ({
      id: item.id,
      qty: qtyText(item.qty),
      amount: item.amount === null ? '' : formatMoney(item.amount),
    })),
  };
}

/** Тело PATCH: вся шапка и позиции; ставку — только если её правили руками. */
export function patchOf(form: AgreementFormState, card: AgreementCard): AgreementPatch {
  const patch: AgreementPatch = {
    counterparty_id: form.counterparty?.id ?? null,
    name: form.name.trim(),
    ext_number: form.ext_number.trim(),
    ext_date: form.ext_date || null,
    agreement_type: form.agreement_type,
    is_open: form.is_open,
    amount: form.is_open ? null : parseMoneyInput(form.amount),
    with_vat: form.with_vat,
    valid_to: form.valid_to || null,
    items: form.items.map((item) => ({
      id: item.id,
      qty: parseQtyInput(item.qty) ?? '0',
      amount: form.is_open ? null : parseMoneyInput(item.amount),
    })),
  };
  if (form.vat_manual) patch.vat_rate = form.vat_rate.replace(',', '.') || null;
  else if (card.vat_source === 'manual') patch.vat_rate = null;
  return patch;
}

/** Ошибки перед отправкой: ключ — поле или `item:<id>`. */
export function submitErrors(form: AgreementFormState, card: AgreementCard): Record<string, string> {
  const errors: Record<string, string> = {};
  const supplement = card.parent !== null;
  if (!form.counterparty) errors.counterparty = 'Выберите контрагента';
  else if (form.counterparty.status !== 'active') errors.counterparty = 'Контрагент не активен';
  if (form.name.trim().length < NAME_MIN) errors.name = 'Наименование — от 3 символов';
  if (!form.ext_number.trim()) errors.ext_number = 'Укажите номер договора';
  if (!form.ext_date) errors.ext_date = 'Укажите дату договора';
  if (form.valid_to && form.ext_date && form.valid_to < form.ext_date) {
    errors.valid_to = 'Срок действия — не раньше даты договора';
  }
  if (!form.agreement_type) errors.agreement_type = 'Выберите тип договора';
  const amount = parseMoneyInput(form.amount);
  if (!form.is_open) {
    if (amount === null || (lessThan(amount, '0.01') && !supplement)) {
      errors.amount = 'Сумма договора — больше нуля';
    }
  }
  if (!supplement && form.items.length === 0) errors.items = 'В договоре нужна хотя бы одна позиция';
  const byId = new Map(card.items.map((item) => [item.id, item]));
  for (const item of form.items) {
    const qty = parseQtyInput(item.qty);
    const available = byId.get(item.id)?.qty_available ?? '0';
    if (qty === null || BigInt(qty.replace('.', '')) <= 0n) {
      errors[`item:${item.id}`] = 'Количество — больше нуля';
    } else if (BigInt(qty.replace('.', '')) > milli(available)) {
      errors[`item:${item.id}`] = `Не больше остатка ${qtyText(available)}`;
    } else if (!form.is_open && parseMoneyInput(item.amount) === null) {
      errors[`item:${item.id}`] = 'Укажите сумму позиции';
    }
  }
  if (!form.is_open && !supplement && amount !== null) {
    const itemsTotal = sumMoney(form.items.map((item) => parseMoneyInput(item.amount)));
    if (itemsTotal !== amount) {
      errors.items_total = `Сумма позиций ${formatMoney(itemsTotal)} не равна сумме договора ${formatMoney(amount)}`;
    }
  }
  return errors;
}

/** Превышение над планом (BR-034): у допсоглашения — весь прирост. */
export function overPlan(form: AgreementFormState, card: AgreementCard): string {
  const amount = parseMoneyInput(form.amount);
  if (form.is_open || amount === null) return '0.00';
  if (card.parent) return amount;
  const plan = sumMoney(card.items.filter((item) => form.items.some((f) => f.id === item.id))
    .map((item) => item.plan_amount));
  const over = subMoney(amount, plan);
  return lessThan(over, 0) ? '0.00' : over;
}

/** Подписи и денежные поля «Истории изменений» договора (ключи `changes`
 * журнала: снимок правки `services/agreements/agreements.py::_snapshot` и
 * факты событий — отправка, расторжение, допсоглашение). */
export const AGREEMENT_HISTORY_FIELDS: HistoryFieldOptions = {
  fieldLabels: {
    counterparty_id: 'Контрагент', counterparty_confirmed: 'Контрагент подтверждён',
    name: 'Наименование', ext_number: 'Номер договора', ext_date: 'Дата договора',
    agreement_type: 'Тип договора', is_open: 'Открытый договор', amount: 'Сумма',
    with_vat: 'С НДС', vat_rate: 'Ставка НДС, %', vat_source: 'Источник ставки НДС',
    valid_to: 'Срок действия по', items: 'Позиции', number: 'Номер',
    over_plan: 'Сверх плана', available_before: 'Свободно в статье до отправки',
    supplement: 'Допсоглашение', status: 'Статус',
  },
  moneyFields: ['amount', 'over_plan', 'available_before'],
};
