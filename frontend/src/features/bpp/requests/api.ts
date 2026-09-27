/**
 * Клиент заявки на закупку модуля БЗО (`/api/bpp/v1/requests`, задача B2.2).
 *
 * Пока — только чтение карточки: его ждёт карточка согласования
 * (`app/signoffSubjectViews`). Формы и реестры заявок строятся на каркасе
 * раздела `/bpp` (A2.1) и дополнят этот файл.
 */

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

/** Деньги и количества приходят строкой (Decimal на сервере). */
export type Money = string;

export interface PurchaseRequestItem {
  id: string;
  line_no: number;
  sys_number: string;
  name: string;
  specs: string;
  uom: string | null;
  qty: string;
  price: Money;
  amount: Money;
  need_date: string;
  status: 'open' | 'partially_closed' | 'closed' | 'annulled';
}

export interface PurchaseRequestCard {
  id: string;
  number: string;
  status: string;
  author_name: string | null;
  created_at: string;
  initiator_role: 'sn' | 'pm';
  project: { id: string; code: string | null; name: string | null };
  article: { id: string; code: string | null; name: string | null; archived: boolean } | null;
  purchase_type: 'goods' | 'works' | '';
  need_date: string | null;
  justification: string;
  currency: string;
  total_amount: Money;
  rework_comment: string;
  budget: {
    limit: Money;
    committed: Money;
    available: Money;
    after_request: Money;
    reserved: boolean;
  } | null;
  items: PurchaseRequestItem[];
  files: { id: string; filename: string; version: number }[];
}

export const bppRequestsApi = {
  get: (id: string) =>
    api.get<PurchaseRequestCard>(apiPath('bpp', `requests/${id}`)).then((r) => r.data),
};
