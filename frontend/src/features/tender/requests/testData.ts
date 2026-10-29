/**
 * Данные для тестов экранов заявки на тендер (T1.4) — карточка по контракту
 * API плана этапов 0–2 §3.4 и ответ справочников. Только для тестов.
 */
import type { TenderRequestCard } from './api';

export const REQUEST_ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';
export const BPP_REQUEST_ID = '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d';

export const requestCard = (over: Partial<TenderRequestCard> = {}): TenderRequestCard => ({
  id: REQUEST_ID, number: 'ЗТ-2026-000007', status: 'draft', status_display: 'Черновик',
  author_id: 904, author_name: 'Иванов А.', created_at: '2026-10-07T09:00:00+05:00',
  updated_at: '2026-10-07T09:00:00+05:00', initiator_role: 'sn',
  project_id: 'p1', project: { id: 'p1', code: 'П-015', name: 'ЖК Нурлы Жол' }, article_id: 'a-metal', purchase_type: 'goods', need_date: '2099-11-01',
  delivery_address: 'Астана, ул. Сарыарка 1', justification: 'Каркас корпуса Б по графику',
  needs_delivery: false, delivery_article_id: null, delivery_plan_amount: null,
  needs_works: false, works_scope: '', works_article_id: null, works_plan_amount: null,
  allow_analogs: false, allow_partial: true, rework_comment: '', status_comment: '',
  version: 4, allowed_actions: ['save', 'submit', 'cancel', 'delete'],
  items: [{
    id: 'i1', line_no: 1, name: 'Швеллер 12П', specs: 'ГОСТ 8240', uom_id: 'uom-t',
    qty: '10.000', plan_price: '365000.00', need_date: '2099-11-01', article_id: null,
  }],
  parts: [],
  ...over,
});

export const ARTICLES = [
  { id: 'a-metal', code: 'T-METAL', name: 'Металлопрокат', group_code: 'supply', available: '5000000.00' },
  { id: 'a-weld', code: 'T-WELD', name: 'Сварочные материалы', group_code: 'supply', available: '800000.00' },
  { id: 'a-logistics', code: 'T-LOG', name: 'Логистика', group_code: 'supply', available: '400000.00' },
];

export const REFDATA_ARTICLES = ARTICLES.map(({ id, code, name }) => ({
  id, code, name, group_id: 'g1', parent_id: null, is_active: true, ext_1c_ref: '',
}));

export const UOMS = [
  { id: 'uom-t', code: 't', short_name: 'т', name: 'Тонна', is_active: true },
  { id: 'uom-pcs', code: 'pcs', short_name: 'шт', name: 'Штука', is_active: true },
];

export const PROJECTS = [{ id: 'p1', code: 'П-015', name: 'ЖК Нурлы Жол' }];

/** Ответ GET по адресу — общий для экранов заявки. */
export function serveReference(url: string): { data: unknown } | null {
  if (url.endsWith('requests/projects')) return { data: PROJECTS };
  if (url.endsWith('requests/articles')) return { data: ARTICLES };
  if (url.endsWith('requests/budget')) {
    return {
      data: { limit: '6000000.00', committed: '1000000.00', available: '5000000.00', currency_code: 'KZT' },
    };
  }
  if (url.includes('refdata/v1/uoms')) return { data: UOMS };
  if (url.includes('refdata/v1/articles')) return { data: REFDATA_ARTICLES };
  if (url.endsWith('bpp/v1/me')) return { data: { article_groups: ['supply'], initiator_roles: ['sn'] } };
  return null;
}
