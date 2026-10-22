/**
 * Формы ответов портала поставщика (`/api/tender/v1/supplier/<token>/…`,
 * план этапа 3 §1, T3.2–T3.4). Плановых цен заказчика, бюджета, чужих
 * приглашений и служебных ключей в ответах нет (белый список сервера).
 * Деньги и количества — строками (Decimal на сервере).
 */
import type { PaymentScheme } from '../tenders/api';

/** `GET supplier/<token>` — промежуточная карточка, ничего не пишет. */
export interface PortalCard {
  company_name: string;
  tender_number: string;
  deadline_at: string | null;
  intake_open: boolean;
  /** Эта cookie устройства уже привязана к приглашению. */
  bound: boolean;
}

export interface PortalItem {
  id: string;
  line_no: number;
  name: string;
  specs: string;
  uom: { code: string; short_name: string } | null;
  qty: string;
  need_date: string | null;
}

export interface PortalFile {
  id: string;
  name: string;
  size: number;
}

/** `GET supplier/<token>/tender` — карточка тендера для поставщика. */
export interface PortalTender {
  /** Заказчик — компания поддомена. */
  customer: string;
  number: string;
  deadline_at: string | null;
  currency_code: string;
  payment_scheme: PaymentScheme | null;
  delivery_terms: string;
  delivery_address: string;
  items: PortalItem[];
  needs_delivery: boolean;
  needs_works: boolean;
  works_scope: string;
  allow_analogs: boolean;
  allow_partial: boolean;
  /** Файлы ТЗ заявки. */
  files: PortalFile[];
  intake_open: boolean;
  /** Статус своего приглашения (`opened`, `submitted`, `declined`, …). */
  participation_status: string;
  /** Итог для поставщика (TND-035): решение не принято, выбран, не выбран,
   * тендер отменён или не состоялся. */
  result: PortalResult | string;
  /** Свои выбранные позиции — только у победителя после утверждения выбора. */
  result_items?: PortalResultItem[];
}

export type PortalResult = 'awaiting' | 'awarded' | 'not_awarded' | 'cancelled' | 'failed';

export interface PortalResultItem {
  line_no: number;
  name: string;
  qty: string;
}

export interface OfferLine {
  item_id: string;
  participates: boolean;
  price: string | null;
  qty: string | null;
  delivery_date: string | null;
  is_analog: boolean;
  analog_note: string;
  comment: string;
}

export type ExtraKind = 'delivery' | 'works';

export interface OfferExtra {
  kind: ExtraKind;
  amount: string | null;
  included_in_price: boolean;
  note: string;
}

export interface Requisites {
  name: string;
  country_code: string;
  reg_number: string;
  is_vat_payer: boolean;
  contact_name: string;
  phone: string;
  email: string;
}

export type OfferStatus = 'draft' | 'submitted' | 'replaced' | 'withdrawn';

export interface OfferVersion {
  number: number;
  status: OfferStatus | string;
  submitted_at: string | null;
}

/** Реквизиты в ответе: незаполненное поле приходит `null`. */
export type PortalRequisites = { [K in keyof Requisites]?: Requisites[K] | null };

/**
 * `GET/PUT supplier/<token>/offer` — черновик или последняя отправленная
 * версия. Предложения нет вовсе (приём закрыт, а поставщик ничего не
 * сохранял) — поля предложения `null`, реквизиты `{}`, признаки — как обычно.
 */
export interface PortalOffer {
  id: string | null;
  version: number | null;
  status: OfferStatus | string | null;
  /** Номер отправки; у черновика `null`. */
  number: number | null;
  submitted_at: string | null;
  /** Можно ли сейчас править (срок не прошёл, тендер принимает предложения). */
  editable: boolean;
  intake_open: boolean;
  /** Поставщик отказался от участия. */
  declined: boolean;
  /** Статус приглашения: `declined` — поставщик отказался. */
  invitation_status: string;
  /** Есть отправленная версия, и её можно отозвать. */
  can_withdraw: boolean;
  currency_code: string | null;
  with_vat: boolean | null;
  vat_rate: string | null;
  valid_until: string | null;
  extra_terms: string;
  lines: OfferLine[];
  extras: OfferExtra[];
  payment_scheme: PaymentScheme | null;
  requisites: PortalRequisites;
  /** Известный контрагент — реквизиты подставлены и не правятся. */
  requisites_readonly: boolean;
  pd_consent: boolean;
  pd_consent_at: string | null;
  history: OfferVersion[];
}

/** Доставка и СМР в `PUT offer` — словарём по виду, только запрошенные. */
export type OfferExtrasInput = Partial<Record<ExtraKind, Omit<OfferExtra, 'kind'>>>;

export interface OfferInput {
  version: number;
  currency_code: string;
  with_vat: boolean;
  vat_rate: string | null;
  valid_until: string | null;
  extra_terms: string;
  lines: OfferLine[];
  extras: OfferExtrasInput;
  payment_scheme: { kind: string; advance_pct?: string; postpay_days?: number } | null;
  requisites?: Requisites;
}
