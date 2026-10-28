/**
 * Окно карточки — типы ленты, запросов доступа и панели «Запросы»
 * (мастер-план §6.2–6.4, этап S2). Сама карточка — `Task` из `@/types/tasks`.
 */
import type { BoardFieldType, TaskAccessKind } from '@/types/tasks';

export interface FeedPerson {
  id: number;
  name: string | null;
  avatar_url?: string | null;
}

export interface FeedComment {
  kind: 'comment';
  id: number;
  created_at: string;
  updated_at: string;
  actor: FeedPerson | null;
  body: string;
}

export interface FeedActivity {
  kind: 'activity';
  id: number;
  created_at: string;
  /** `null` — изменение сделала автоматизация (этап S4). */
  actor: FeedPerson | null;
  field: string;
  old: string | null;
  new: string | null;
  /** Имена за id людей и отделов; остальное фронт показывает сам. */
  old_label: string | null;
  new_label: string | null;
  /** Строка своего поля доски (`field:<id>`, этап S3): название и тип; у
   * удалённого поля — `null`. */
  board_field?: { id: number; name: string | null; type: BoardFieldType | null } | null;
  /** Правку сделала автоматизация доски (этап S4): правило и его название. */
  automation?: { id: number; name: string | null } | null;
}

export type FeedEntry = FeedComment | FeedActivity;

export interface FeedPage {
  items: FeedEntry[];
  next_before: string | null;
}

export type AccessRequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface AccessRequest {
  id: number;
  task: { id: number; key: string; summary: string };
  requester: { id: number; name: string | null } | null;
  kind: TaskAccessKind;
  comment: string;
  status: AccessRequestStatus;
  approve_mode: 'replace' | 'delegate' | null;
  replaced: { id: number; name: string | null } | null;
  decided_by: { id: number; name: string | null } | null;
  decided_at: string | null;
  decision_comment: string;
  created_at: string;
}

export interface RequestsInbox {
  to_decide: AccessRequest[];
  mine: AccessRequest[];
  to_decide_count: number;
}

export type HistoryItem =
  | { type: 'request'; at: string; request: AccessRequest }
  | {
      type: 'transfer';
      at: string;
      task: { id: number; key: string; summary: string };
      by: { id: number; name: string | null } | null;
      from: { id: number; name: string | null } | null;
      to: { id: number; name: string | null } | null;
    };

export interface PersonOption {
  id: number;
  full_name: string;
  email: string;
  username?: string;
}
