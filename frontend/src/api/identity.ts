/* ------------------------------------------------------------------ */
/*  Сверка идентичности Сотрудник ↔ Аккаунт                            */
/* ------------------------------------------------------------------ */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';

const HR = `${API_ENDPOINTS.hr}/`;

export type IdentityRequestStatus = 'pending' | 'applied' | 'rejected';
export type IdentityRequestSource = 'hr_form' | 'nightly';
export type IdentityDecision = 'apply' | 'reject';

export interface IdentityRequestField {
  field: string;
  proposed_value: string;
  /** Снимок значения аккаунта на момент подачи заявки. */
  account_value_at_request: string;
  /** Живое значение аккаунта — читается при открытии карточки. */
  account_value_now: string;
  /** true — владелец успел измениться, пока заявка ждала. */
  is_stale: boolean;
  decision: IdentityDecision | null;
}

export interface IdentityRequest {
  id: number;
  employee_id: number;
  employee_name: string;
  department_id: number | null;
  user_id: number;
  status: IdentityRequestStatus;
  source: IdentityRequestSource;
  created_by: number | null;
  created_at: string;
  decided_by: number | null;
  decided_at: string | null;
  decision_note: string | null;
  /** Приходит только в карточке одной заявки, не в списке. */
  fields?: IdentityRequestField[];
}

export interface IdentityApprover {
  user_id: number | null;
  user: { id: number; full_name: string; email: string } | null;
}

export const fetchIdentityRequests = async (
  status: IdentityRequestStatus | 'all' = 'pending',
): Promise<IdentityRequest[]> => {
  const res = await api.get(`${HR}identity-requests/`, { params: { status } });
  return Array.isArray(res.data) ? res.data : [];
};

export const fetchIdentityRequest = async (id: number): Promise<IdentityRequest> => {
  const res = await api.get(`${HR}identity-requests/${id}/`);
  return res.data;
};

export const decideIdentityRequest = async (
  id: number,
  decisions: Record<string, IdentityDecision>,
  note?: string,
): Promise<IdentityRequest> => {
  const res = await api.post(`${HR}identity-requests/${id}/decide`, { decisions, note });
  return res.data;
};

export const fetchIdentityApprover = async (): Promise<IdentityApprover> => {
  const res = await api.get(`${HR}identity-approver/`);
  return res.data;
};

export const setIdentityApprover = async (userId: number | null): Promise<IdentityApprover> => {
  const res = await api.put(`${HR}identity-approver/`, { user_id: userId });
  return res.data;
};
