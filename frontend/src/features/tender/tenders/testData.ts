/**
 * Данные для тестов экранов тендера (T2.3) — по контракту API плана этапов
 * 0–2 §4.3 (формы ответов согласованы с ведущим). Только для тестов.
 */
import type { Counterparty, Invitation, SupplierContact, TenderCard } from './api';

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
