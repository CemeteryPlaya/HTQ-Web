/**
 * Клиент подотчётных средств модуля БЗО (`/api/bpp/v1/accountable`, B4.1).
 * Пока — чтение карточки для карточки согласования и прямой ссылки.
 */

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export interface AdvanceReportRow {
  id: string;
  expense_name: string;
  amount: string;
  approval_state: string;
  created_at: string;
}

export interface AccountableCard {
  id: string;
  number: string;
  status: 'draft' | 'on_review' | 'awaiting_accounting' | 'awaiting_report' | 'closed';
  article_name: string;
  amount: string;
  currency: string;
  goal: string;
  paid_at: string | null;
  reported_amount: string;
  remaining_amount: string;
  reports: AdvanceReportRow[];
  created_at: string;
}

export const bppAccountableApi = {
  get: (id: string) =>
    api.get<AccountableCard>(apiPath('bpp', `accountable/${id}`)).then((r) => r.data),
};
