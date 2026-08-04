/**
 * Shared types for the unified Email UI.
 * Mirrors the Pydantic schemas in services/email/app/schemas/account.py.
 */

export type EmailAccountType = 'corporate' | 'personal';
// 'imap' — ящик, подключённый пользователем по IMAP/SMTP (свой сервер).
// Без него тип врал про то, что реально приходит с бэкенда.
export type EmailAccountProvider = 'mailcow' | 'imap' | 'google' | 'microsoft';

export type Folder = 'inbox' | 'sent' | 'drafts' | 'trash' | 'archive' | 'spam';

export interface EmailAccount {
  id: number;
  type: EmailAccountType;
  provider: EmailAccountProvider;
  address: string;
  display_name: string | null;
  is_default: boolean;
  is_active: boolean;
  last_sync_at: string | null;
  last_sync_error: string | null;
  watch_expires_at: string | null;
  connected_at: string;
  unread_count: number;
}

export interface EmailAccountSyncResponse {
  account_id: number;
  queued_at: string;
  status: 'queued';
}

/** Stored under localStorage['htq.email.activeAccountId']. 'all' = unified view. */
export type ActiveAccountId = number | 'all';

export interface EmailRecipient {
  email: string;
  name?: string | null;
}

export interface EmailMessageSummary {
  id: string; // UUID
  account_id: number | null;
  subject: string;
  snippet: string;
  sender_email: string;
  sender_name: string | null;
  to_recipients: EmailRecipient[];
  cc_recipients: EmailRecipient[];
  date: string;
  is_read: boolean;
  is_flagged: boolean;
  has_attachments: boolean;
  folder: Folder;
  provider_folder?: string | null;
}

export interface EmailAttachmentInfo {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
}

export interface EmailMessageDetail extends EmailMessageSummary {
  body_html: string | null;
  body_text: string | null;
  attachments: EmailAttachmentInfo[];
}

export interface UnreadCounts {
  by_account: Record<string, number>;
  by_folder: Record<string, number>;
}

export interface SendMessagePayload {
  account_id: number;
  to_recipients: EmailRecipient[];
  cc_recipients?: EmailRecipient[];
  bcc_recipients?: EmailRecipient[];
  subject: string;
  body_text?: string;
  body_html?: string;
}
