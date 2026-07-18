import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';

const EMAIL = `${API_ENDPOINTS.email}/`;

export interface UserBasic {
    id: number;
    username: string;
    email: string;
    first_name: string;
    last_name: string;
}

export interface EmailAttachment {
    id: number;
    file: string; // URL
    name?: string;
    uploaded_at: string;
}

export interface EmailMessage {
    id: number;
    subject: string;
    body: string;
    sender: UserBasic;
    is_draft: boolean;
    created_at: string;
    sent_at: string | null;
    attachments: EmailAttachment[];
    external_recipients: string[];
}

export interface EmailRecipientStatus {
    id: number;
    message: EmailMessage;
    user: UserBasic;
    recipient_type: 'to' | 'cc' | 'bcc';
    folder: 'inbox' | 'archive' | 'trash';
    is_read: boolean;
    read_at: string | null;
}

export interface OAuthStatus {
    connected: boolean;
    provider: 'google' | 'microsoft' | null;
    email: string | null;
    primary_email: string | null;
    connected_at?: string;
    token_expires_at?: string;
}

export interface OAuthInitResponse {
    auth_url: string;
    provider: string;
    state: string;
}

export interface OAuthCallbackResponse {
    status: string;
    provider: string;
    address: string;
    account_id: number;
}

// Helper: backend exposes `GET /api/email/v1/folder/{folder}` and returns
// a plain list. Keep a pseudo-Paginated<T> result-type so callers using
// `.results` on legacy code still compile, but unwrap defensively.
function listOrEmpty<T>(data: unknown): T[] {
    if (Array.isArray(data)) return data as T[];
    if (data && typeof data === 'object') {
        const d = data as Record<string, unknown>;
        if (Array.isArray(d.results)) return d.results as T[];
        if (Array.isArray(d.items)) return d.items as T[];
    }
    return [];
}

export const emailService = {
    getInbox: async () => {
        const response = await api.get<unknown>(`${EMAIL}folder/inbox`);
        return listOrEmpty<EmailRecipientStatus>(response.data);
    },
    getSent: async () => {
        const response = await api.get<unknown>(`${EMAIL}folder/sent`);
        return listOrEmpty<EmailMessage>(response.data);
    },
    getDrafts: async () => {
        const response = await api.get<unknown>(`${EMAIL}folder/drafts`);
        return listOrEmpty<EmailMessage>(response.data);
    },
    getTrash: async () => {
        const response = await api.get<unknown>(`${EMAIL}folder/trash`);
        return listOrEmpty<EmailRecipientStatus>(response.data);
    },
    sendEmail: async (data: FormData) => {
        const response = await api.post<EmailMessage>(`${EMAIL}send`, data, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },
    saveDraft: async (data: { subject: string; body: string }) => {
        const response = await api.post<EmailMessage>(`${EMAIL}draft`, data);
        return response.data;
    },
    markAsRead: async (statusId: number, is_read: boolean = true) => {
        const response = await api.post<EmailRecipientStatus>(
            `${EMAIL}${statusId}/read`,
            { is_read },
        );
        return response.data;
    },

    // ── OAuth 2.0 ──
    getOAuthStatus: async (): Promise<OAuthStatus> => {
        const response = await api.get<OAuthStatus>(`${EMAIL}oauth/status`);
        return response.data;
    },
    initiateOAuth: async (provider: 'google' | 'microsoft'): Promise<OAuthInitResponse> => {
        const response = await api.post<OAuthInitResponse>(`${EMAIL}oauth/connect/${provider}`);
        return response.data;
    },
    handleOAuthCallback: async (code: string, state: string): Promise<OAuthCallbackResponse> => {
        const response = await api.get<OAuthCallbackResponse>(
            `${EMAIL}oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
        );
        return response.data;
    },
    disconnectOAuth: async (): Promise<{ status: string }> => {
        const response = await api.delete<{ status: string }>(`${EMAIL}oauth/disconnect`);
        return response.data;
    },
};
