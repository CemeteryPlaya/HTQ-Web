/**
 * Typed HTTP client for the email service.
 *
 * This file gradually replaces frontend/src/services/emailService.ts as the
 * Email page is rebuilt around the unified `email_accounts` API. Callers
 * should prefer this module + the hooks under `pages/Email/hooks/`.
 */

import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
  EmailAccount,
  EmailAccountSyncResponse,
  EmailMessageDetail,
  EmailMessageSummary,
  Folder,
  SendMessagePayload,
  UnreadCounts,
} from '@/pages/Email/types';

const BASE = `${API_ENDPOINTS.email}/`;

interface ListMessagesParams {
  folder: Folder;
  accountId?: number | null;
  limit?: number;
  offset?: number;
}

export const emailApi = {
  // ── Accounts ─────────────────────────────────────────────────────────
  listAccounts: async (): Promise<EmailAccount[]> => {
    const res = await api.get<EmailAccount[]>(`${BASE}accounts/`);
    return Array.isArray(res.data) ? res.data : [];
  },

  setDefaultAccount: async (accountId: number): Promise<EmailAccount> => {
    const res = await api.post<EmailAccount>(
      `${BASE}accounts/${accountId}/set-default/`,
    );
    return res.data;
  },

  syncAccount: async (accountId: number): Promise<EmailAccountSyncResponse> => {
    const res = await api.post<EmailAccountSyncResponse>(
      `${BASE}accounts/${accountId}/sync/`,
    );
    return res.data;
  },

  disconnectAccount: async (accountId: number): Promise<void> => {
    await api.delete(`${BASE}accounts/${accountId}/`);
  },

  // ── OAuth (start the connect flow) ───────────────────────────────────
  startConnect: async (
    provider: 'google' | 'microsoft',
  ): Promise<{ auth_url: string; provider: string; state: string }> => {
    const res = await api.post<{ auth_url: string; provider: string; state: string }>(
      `${BASE}oauth/connect/${provider}`,
    );
    return res.data;
  },

  // ── Messages ─────────────────────────────────────────────────────────
  listMessages: async ({
    folder,
    accountId,
    limit = 50,
    offset = 0,
  }: ListMessagesParams): Promise<EmailMessageSummary[]> => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    if (accountId !== undefined && accountId !== null) {
      params.set('account_id', String(accountId));
    }
    const res = await api.get<EmailMessageSummary[]>(
      `${BASE}folder/${folder}?${params.toString()}`,
    );
    return Array.isArray(res.data) ? res.data : [];
  },

  getMessage: async (messageId: string): Promise<EmailMessageDetail> => {
    const res = await api.get<EmailMessageDetail>(`${BASE}${messageId}`);
    return res.data;
  },

  markAsRead: async (messageId: string): Promise<void> => {
    await api.post(`${BASE}${messageId}/read`);
  },

  unreadCounts: async (): Promise<UnreadCounts> => {
    const res = await api.get<UnreadCounts>(`${BASE}unread-counts/`);
    return res.data;
  },

  send: async (payload: SendMessagePayload): Promise<{ status: string; id: string }> => {
    const res = await api.post<{ status: string; id: string }>(
      `${BASE}send`,
      payload,
    );
    return res.data;
  },
};
