/**
 * Данные для тестов портала поставщика (T3.5) — по контракту плана этапа 3
 * (§1, T3.2–T3.4) и формам, записанным в отчёте T3.5. Только для тестов.
 */
import type { PortalCard, PortalOffer, PortalTender } from './types';

/** Ответ `fetch` без зависимостей от Response окружения: только то, что читает клиент. */
export function fakeResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  const lower = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => lower[name.toLowerCase()] ?? null },
    text: () => Promise.resolve(body === null ? '' : typeof body === 'string' ? body : JSON.stringify(body)),
  };
}

export const TOKEN = 'k3J9-token_value';

export const portalCard = (over: Partial<PortalCard> = {}): PortalCard => ({
  company_name: 'ТОО «Hi-Tech Qazaqstan»', tender_number: 'ТН-2026-000003',
  deadline_at: '2099-11-20T13:00:00+00:00', intake_open: true, bound: false,
  ...over,
});

export const portalTender = (over: Partial<PortalTender> = {}): PortalTender => ({
  customer: 'ТОО «Hi-Tech Qazaqstan»', number: 'ТН-2026-000003',
  deadline_at: '2099-11-20T13:00:00+00:00', currency_code: 'KZT',
  payment_scheme: { kind: 'prepay', stages: [{ order: 1, trigger: 'before_shipment', pct: '100.00', days: null }], postpay_days: null },
  delivery_terms: 'DAP объект', delivery_address: 'Астана, ул. Сарыарка 1',
  items: [
    { id: 'it-1', line_no: 1, name: 'Швеллер 12П', specs: 'ГОСТ 8240', uom: { code: 't', short_name: 'т' }, qty: '10.000', need_date: '2099-11-25' },
    { id: 'it-2', line_no: 2, name: 'Уголок 50×5', specs: '', uom: { code: 't', short_name: 'т' }, qty: '2.500', need_date: '2099-11-25' },
  ],
  needs_delivery: true, needs_works: false, works_scope: '',
  allow_analogs: true, allow_partial: true,
  files: [{ id: 'doc-1', name: 'ТЗ.pdf', size: 120_000 }],
  intake_open: true, participation_status: 'opened', result: 'awaiting',
  ...over,
});

export const portalOffer = (over: Partial<PortalOffer> = {}): PortalOffer => ({
  id: 'of-1', version: 3, status: 'draft', number: null, submitted_at: null, editable: true,
  intake_open: true, declined: false, can_withdraw: false, invitation_status: 'opened',
  currency_code: 'KZT', with_vat: true, vat_rate: '12.00', valid_until: '2099-12-31',
  extra_terms: '',
  lines: [
    { item_id: 'it-1', participates: true, price: null, qty: '10.000', delivery_date: null, is_analog: false, analog_note: '', comment: '' },
    { item_id: 'it-2', participates: true, price: null, qty: '2.500', delivery_date: null, is_analog: false, analog_note: '', comment: '' },
  ],
  extras: [{ kind: 'delivery', amount: null, included_in_price: true, note: '' }],
  payment_scheme: null,
  requisites: {
    name: 'ТОО «Сталь Трейд»', country_code: 'KZ', reg_number: '123456789012', is_vat_payer: true,
    contact_name: 'Ахметов Б.', phone: '+77010000000', email: 'tender@stal.kz',
  },
  requisites_readonly: true,
  pd_consent: false,
  pd_consent_at: null,
  history: [],
  ...over,
});
