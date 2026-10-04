/**
 * Клиент плана закупок модуля БЗО (`/api/bpp/v1/plan`, ТЗ §08, B2.3).
 *
 * План — представление позиций утверждённых заявок с остатком > 0: у СН и
 * ПМ — свои позиции в роли инициатора, у ФД (`bpp.plan.all`) — все, только
 * просмотр (`read_only`). Выбор проверяет сервер (`plan/validate`, BR-021):
 * ответ — заготовка мастера F-03.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { InitiatorRole } from '../requests/api';

export const PLAN_ENDPOINT = apiPath('bpp', 'plan');

export type PlanTarget = 'contract' | 'invoice';

export interface PlanItem {
  id: string;
  sys_number: string;
  request_id: string;
  request_number: string;
  project_id: string;
  project_code: string | null;
  article_id: string | null;
  article_name: string | null;
  name: string;
  uom: string | null;
  qty: string;
  qty_in_agreements: string;
  qty_in_invoices: string;
  qty_left: string;
  amount: string;
  amount_in_invoices: string;
  amount_left: string;
  need_date: string;
  overdue: boolean;
  purchase_type: 'goods' | 'works' | '';
  in_agreement_on_review: boolean;
  executor_id: number;
  executor_name: string | null;
  selectable: boolean;
}

export interface PlanPage {
  items: PlanItem[];
  total: number;
  page: number;
  page_size: number;
  read_only: boolean;
}

export interface PlanSelection {
  ok: true;
  target: PlanTarget;
  project_id: string;
  article_id: string;
  purchase_type: 'goods' | 'works' | null;
  items: { id: string; sys_number: string; name: string; qty_left: string; amount_left: string }[];
}

export const planApi = {
  list: (params: Record<string, string | number>) =>
    api.get<PlanPage>(PLAN_ENDPOINT, { params }).then((r) => r.data),
  validate: (itemIds: string[], target: PlanTarget, role: InitiatorRole | null) =>
    api.post<PlanSelection>(apiPath('bpp', 'plan/validate'), {
      item_ids: itemIds, target, ...(role ? { role } : {}),
    }).then((r) => r.data),
};
