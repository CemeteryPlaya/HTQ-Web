/**
 * Форма предложения поставщика (T3.5; план этапа 3, T3.3) — отдельно от
 * экрана, чтобы проверять без рендера.
 *
 * - Строка формы — на каждую позицию тендера (в порядке позиций), даже если
 *   в черновике её ещё нет: по умолчанию «участвую» и полное количество.
 * - Проверки повторяют серверные (цена > 0 у участвующей, кол-во ≤
 *   запрошенного, аналог и частичное — только если разрешены, срок действия
 *   не в прошлом) — сервер всё равно проверит сам.
 * - Деньги — в копейках без `float` (`lineAmount`, `sumMoney` модуля БЗО).
 */
import { lessThan, sumMoney } from '@/features/bpp/budgets/cents';
import { formatMoney, parseMoneyInput } from '@/features/bpp/format';
import { lineAmount, parseQtyInput } from '@/features/bpp/requests/requestForm';

import { schemeDraftOf, schemeErrors, schemeInput, type SchemeDraft } from '../tenders/schemes';
import type {
  ExtraKind, OfferExtra, OfferExtrasInput, OfferInput, PortalOffer, PortalRequisites, PortalTender,
  Requisites,
} from './types';

export interface LineForm {
  item_id: string;
  participates: boolean;
  price: string;
  qty: string;
  delivery_date: string;
  is_analog: boolean;
  analog_note: string;
  comment: string;
}

export interface ExtraForm {
  amount: string;
  included_in_price: boolean;
  note: string;
}

export interface OfferForm {
  currency_code: string;
  with_vat: boolean;
  vat_rate: string;
  valid_until: string;
  extra_terms: string;
  lines: LineForm[];
  /** `null` — заказчик доставку не запрашивал. */
  delivery: ExtraForm | null;
  /** `null` — заказчик СМР не запрашивал. */
  works: ExtraForm | null;
  scheme: SchemeDraft;
  requisites: Requisites;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** `'2.500'` → `'2,5'`, `'10.000'` → `'10'`. */
export function formatQty(value: string | null | undefined): string {
  if (!value) return '';
  return value.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '').replace('.', ',');
}

const qtyText = (value: string | null) => (value ? value.replace('.', ',') : '');
const moneyText = (value: string | null) => (value ? formatMoney(value) : '');

function extraOf(offer: PortalOffer, kind: ExtraKind, included: boolean): ExtraForm {
  const found = offer.extras.find((extra) => extra.kind === kind);
  return found
    ? { amount: moneyText(found.amount), included_in_price: found.included_in_price, note: found.note }
    : { amount: '', included_in_price: included, note: '' };
}

/** Реквизиты ответа → поля формы: `null` и отсутствующие — пустые. */
function requisitesOf(value: PortalRequisites): Requisites {
  return {
    name: value.name ?? '', country_code: value.country_code ?? '',
    reg_number: value.reg_number ?? '', is_vat_payer: value.is_vat_payer ?? false,
    contact_name: value.contact_name ?? '', phone: value.phone ?? '', email: value.email ?? '',
  };
}

export function formOf(tender: PortalTender, offer: PortalOffer): OfferForm {
  const byItem = new Map(offer.lines.map((line) => [line.item_id, line]));
  return {
    currency_code: offer.currency_code || tender.currency_code || 'KZT',
    with_vat: offer.with_vat ?? false,
    vat_rate: moneyText(offer.vat_rate),
    valid_until: offer.valid_until ?? '',
    extra_terms: offer.extra_terms,
    lines: tender.items.map((item) => {
      const line = byItem.get(item.id);
      return line
        ? {
          item_id: item.id, participates: line.participates, price: moneyText(line.price),
          qty: qtyText(line.qty ?? item.qty), delivery_date: line.delivery_date ?? '',
          is_analog: line.is_analog, analog_note: line.analog_note, comment: line.comment,
        }
        : {
          item_id: item.id, participates: true, price: '', qty: qtyText(item.qty),
          delivery_date: '', is_analog: false, analog_note: '', comment: '',
        };
    }),
    delivery: tender.needs_delivery ? extraOf(offer, 'delivery', true) : null,
    works: tender.needs_works ? extraOf(offer, 'works', false) : null,
    // Своей схемы ещё нет — предлагаем желаемую схему заказчика.
    scheme: schemeDraftOf(offer.payment_scheme ?? tender.payment_scheme),
    requisites: requisitesOf(offer.requisites ?? {}),
  };
}

function extraInput(extra: ExtraForm): Omit<OfferExtra, 'kind'> {
  return {
    amount: extra.included_in_price ? null : parseMoneyInput(extra.amount),
    included_in_price: extra.included_in_price,
    note: extra.note.trim(),
  };
}

/** Сервер ждёт словарь по виду (`extras.delivery`, `extras.works`), не список. */
function extrasInput(form: OfferForm): OfferExtrasInput {
  const out: OfferExtrasInput = {};
  if (form.delivery) out.delivery = extraInput(form.delivery);
  if (form.works) out.works = extraInput(form.works);
  return out;
}

export function offerInput(form: OfferForm, version: number, options: { requisitesEditable: boolean }): OfferInput {
  const body: OfferInput = {
    version,
    currency_code: form.currency_code,
    with_vat: form.with_vat,
    vat_rate: form.with_vat ? parseMoneyInput(form.vat_rate) : null,
    valid_until: form.valid_until || null,
    extra_terms: form.extra_terms.trim(),
    lines: form.lines.map((line) => (line.participates
      ? {
        item_id: line.item_id, participates: true, price: parseMoneyInput(line.price),
        qty: parseQtyInput(line.qty), delivery_date: line.delivery_date || null,
        is_analog: line.is_analog, analog_note: line.is_analog ? line.analog_note.trim() : '',
        comment: line.comment.trim(),
      }
      : {
        item_id: line.item_id, participates: false, price: null, qty: null, delivery_date: null,
        is_analog: false, analog_note: '', comment: line.comment.trim(),
      })),
    extras: extrasInput(form),
    payment_scheme: form.scheme.kind ? schemeInput(form.scheme) : null,
  };
  if (options.requisitesEditable) {
    body.requisites = {
      ...form.requisites,
      name: form.requisites.name.trim(),
      email: form.requisites.email.trim(),
      reg_number: form.requisites.reg_number.trim(),
      country_code: form.requisites.country_code.trim().toUpperCase(),
    };
  }
  return body;
}

/** Сумма указана (0 — тоже сумма: «доставка бесплатно»), как требует сервер. */
const given = (text: string) => {
  const value = parseMoneyInput(text);
  return value !== null && !lessThan(value, '0');
};

const positive = (text: string) => {
  const value = parseMoneyInput(text);
  return value !== null && lessThan('0', value);
};

/** Количество в тысячных как BigInt; `null` — не число. */
const milli = (text: string | null) => {
  const parsed = parseQtyInput(text ?? '');
  return parsed === null ? null : BigInt(parsed.replace('.', ''));
};

/**
 * Проверки перед «Отправить»: ключ — поле (`valid_until`, `delivery`, …),
 * `line:<item_id>` или поля схемы оплаты (`kind`, `advance_pct`,
 * `postpay_days`); пустой объект — можно отправлять.
 */
export function offerErrors(
  form: OfferForm, tender: PortalTender, today: string,
  options: { requisitesEditable?: boolean } = {},
): Record<string, string> {
  const errors: Record<string, string> = {};
  const requested = new Map(tender.items.map((item) => [item.id, item.qty]));

  const participating = form.lines.filter((line) => line.participates);
  if (participating.length === 0) {
    errors.lines = 'Отметьте хотя бы одну позицию, по которой делаете предложение';
  } else if (!tender.allow_partial && participating.length < form.lines.length) {
    errors.lines = 'Частичное предложение не допускается: предложите все позиции';
  }

  for (const line of participating) {
    const asked = requested.get(line.item_id) ?? null;
    const qty = milli(line.qty);
    const limit = milli(asked);
    let problem: string | null = null;
    if (!positive(line.price)) {
      problem = 'Укажите цену за единицу больше нуля';
    } else if (qty === null || qty <= 0n || (limit !== null && qty > limit)) {
      problem = `Количество — больше нуля и не больше запрошенного (${formatQty(asked)})`;
    } else if (!tender.allow_partial && limit !== null && qty < limit) {
      problem = `Частичное предложение не допускается: нужно полное количество (${formatQty(asked)})`;
    } else if (line.is_analog && !tender.allow_analogs) {
      problem = 'Аналоги не допускаются условиями тендера';
    } else if (line.is_analog && !line.analog_note.trim()) {
      problem = 'Опишите аналог: марка, производитель, отличия';
    }
    if (problem) errors[`line:${line.item_id}`] = problem;
  }

  if (!form.valid_until || form.valid_until < today) {
    errors.valid_until = 'Срок действия предложения — не раньше сегодняшнего дня';
  }
  if (form.with_vat) {
    const rate = parseMoneyInput(form.vat_rate);
    if (rate === null || lessThan(rate, '0') || lessThan('100', rate)) {
      errors.vat_rate = 'Ставка НДС — число от 0 до 100';
    }
  }
  if (form.delivery && !form.delivery.included_in_price && !given(form.delivery.amount)) {
    errors.delivery = 'Укажите стоимость доставки или отметьте «включена в цену»';
  }
  if (form.works && !form.works.included_in_price && !given(form.works.amount)) {
    errors.works = 'Укажите стоимость СМР или отметьте «включена в цену»';
  }
  Object.assign(errors, schemeErrors(form.scheme));
  if (options.requisitesEditable) {
    if (form.requisites.name.trim().length < 2) errors['requisites.name'] = 'Укажите наименование организации';
    if (!EMAIL.test(form.requisites.email.trim())) errors['requisites.email'] = 'Укажите e-mail вида name@example.kz';
  }
  return errors;
}

/** Сумма предложения: Σ цена × кол-во участвующих + доставка и СМР не в цене. */
export function offerTotal(form: OfferForm): string {
  const lines = form.lines
    .filter((line) => line.participates)
    .map((line) => lineAmount(line.qty, line.price));
  const extra = (value: ExtraForm | null) =>
    (value && !value.included_in_price ? parseMoneyInput(value.amount) : null);
  return sumMoney([...lines, extra(form.delivery), extra(form.works)]);
}
