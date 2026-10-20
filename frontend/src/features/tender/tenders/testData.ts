/**
 * Данные для тестов экранов тендера (T2.3) — по контракту API плана этапов
 * 0–2 §4.3 (формы ответов согласованы с ведущим). Только для тестов.
 */
import type { Counterparty, Invitation, SupplierContact, TenderCard } from './api';
import type { AwardView, Comparison, ComparisonSupplier } from './comparison';

export const TENDER_ID = '7c9e6679-7425-40de-944b-e07fc1f90ae7';
export const REQUEST_ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

export const invitation = (over: Partial<Invitation> = {}): Invitation => ({
  id: 'inv-1', counterparty_id: 'cp-1', prospect_id: null, name: 'ТОО «Металл-Снаб»',
  email: 'sales@metall.kz', status: 'created', sent_at: null, first_opened_at: null,
  revoked_at: null, max_devices: 1, allowed_actions: [],
  ...over,
});

export const tenderCard = (over: Partial<TenderCard> = {}): TenderCard => ({
  id: TENDER_ID, number: 'ТН-2026-000003', status: 'draft', status_display: 'Черновик',
  request_id: REQUEST_ID, request_number: 'ЗТ-2026-000007', request_status: 'approved',
  author_id: 904, deadline_at: '2099-11-20T13:00:00+00:00', currency_code: 'KZT',
  delivery_terms: 'DAP Астана', quality_reviewer_user_id: null, quality_reviewer_name: null,
  cancel_reason: '', opened_at: null, created_at: '2026-10-07T09:00:00+00:00', round: 1,
  version: 2, allowed_actions: ['edit', 'publish', 'cancel', 'invite'],
  payment_scheme: { kind: 'prepay', stages: [{ order: 1, trigger: 'before_shipment', pct: '100.00', days: null }], postpay_days: null },
  counters: { sent: 0, opened: 0, submitted: 0 },
  invitations: [invitation()],
  ...over,
});

export const COUNTERPARTIES: Counterparty[] = [
  {
    id: 'cp-2', name: 'ТОО «Сталь Трейд»', short_name: 'Сталь Трейд', reg_number: '123456789012',
    country_code: 'KZ', status: 'active', email: 'info@stal.kz', contact_person: 'Ахметов Б.',
    phone: '+77010000000',
  },
  {
    id: 'cp-3', name: 'ТОО «Закрытая лавка»', short_name: 'Лавка', reg_number: '210987654321',
    country_code: 'KZ', status: 'blocked', email: 'shop@lavka.kz', contact_person: '', phone: '',
  },
];

export const CONTACTS: SupplierContact[] = [
  { id: 'ct-1', counterparty_id: 'cp-2', email: 'tender@stal.kz', name: 'Отдел продаж', phone: '', is_primary: true, is_active: true },
  { id: 'ct-2', counterparty_id: 'cp-2', email: 'old@stal.kz', name: 'Бывший менеджер', phone: '', is_primary: false, is_active: false },
];

export const PROSPECTS = [
  { id: 'pr-1', name: 'ИП Новый поставщик', email: 'new@supplier.kz', reg_number: '', country_code: 'KZ', counterparty_id: null, version: 1 },
];

// ── этап 5: сравнение и выбор ───────────────────────────────────────────

export const supplier = (over: Partial<ComparisonSupplier> = {}): ComparisonSupplier => ({
  invitation_id: 'inv-a', name: 'ТОО «Альфа»', counterparty_id: 'cp-a', prospect_id: null,
  offer_id: 'of-a', offer_number: 'КП-1', currency_code: 'KZT', rate: '1', rate_on: '2026-10-20',
  with_vat: true, vat_rate: '12', valid_until: '2099-01-01', valid_expired: false,
  payment_scheme: { kind: 'prepay', stages: [], postpay_days: null },
  coverage: { offered: 2, total: 2 }, total_common_kzt: '1200.00', total_full_kzt: '1200.00',
  saving_common_kzt: '300.00', files: [], requisites: {}, extra_terms: '',
  ...over,
});

export const comparisonData = (over: Partial<Comparison> = {}): Comparison => ({
  tender_id: TENDER_ID, rate_date: '2026-10-20', opened_at: '2026-10-20T10:00:00+05:00',
  suppliers: [
    supplier(),
    supplier({ invitation_id: 'inv-b', name: 'ТОО «Бета»', offer_id: 'of-b', offer_number: 'КП-2',
      currency_code: 'USD', rate: '500', total_common_kzt: '1500.00', total_full_kzt: '1500.00',
      saving_common_kzt: '-100.00', coverage: { offered: 1, total: 2 } }),
  ],
  items: [
    {
      item_id: 'it-1', line_no: 1, name: 'Арматура А500', specs: '', uom: { code: 't', short_name: 'т' },
      qty: '10', plan_price: '100', plan_amount: '1000', in_common_set: true,
      cheapest_invitation_id: 'inv-a',
      offers: {
        'inv-a': { participates: true, line_id: 'ln-a1', price: '90', qty: '10', partial_qty: false,
          amount: '1008.00', amount_kzt: '1008.00', unit_price_kzt: '90', delivery_date: null,
          is_analog: false, analog_note: '', comment: '' },
        'inv-b': { participates: true, line_id: 'ln-b1', price: '0.2', qty: '6', partial_qty: true,
          amount: '1.34', amount_kzt: '672.00', unit_price_kzt: '100', delivery_date: '2026-11-01',
          is_analog: true, analog_note: 'Аналог ГОСТ', comment: '' },
      },
    },
    {
      item_id: 'it-2', line_no: 2, name: 'Швеллер 12П', specs: '', uom: { code: 't', short_name: 'т' },
      qty: '2', plan_price: '100', plan_amount: '200', in_common_set: false,
      cheapest_invitation_id: 'inv-a',
      offers: {
        'inv-a': { participates: true, line_id: 'ln-a2', price: '95', qty: '2', partial_qty: false,
          amount: '212.80', amount_kzt: '212.80', unit_price_kzt: '95', delivery_date: null,
          is_analog: false, analog_note: '', comment: '' },
        'inv-b': { participates: false },
      },
    },
  ],
  extras: [{
    kind: 'delivery', plan_amount: '50', cheapest_invitation_id: 'inv-a',
    offers: {
      'inv-a': { extra_id: 'ex-a', included_in_price: false, amount: '40', amount_kzt: '40', note: '' },
      'inv-b': { extra_id: 'ex-b', included_in_price: true, amount: '0', amount_kzt: '0', note: '' },
    },
  }],
  totals: { declined: [{ invitation_id: 'inv-c', name: 'ТОО «Гамма»', reason: 'Нет на складе' }], suppliers: 2 },
  warnings: [],
  ...over,
});

export const awardView = (over: Partial<AwardView> = {}): AwardView => ({
  tender_id: TENDER_ID, version: 5, status: 'opened', comment: '', status_comment: '',
  lines: [], extras: [], suppliers: [], parts: [], allowed_actions: ['cancel', 'award'],
  ...over,
});
