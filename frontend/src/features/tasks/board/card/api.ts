/**
 * Клиент окна карточки (мастер-план §6.2–6.4, этап S2): чек-листы, лента,
 * запросы доступа, выключатель уведомлений доски, поиск людей. Сама карточка
 * и её правка — существующие функции `@/api/tasks`.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import type { Checklist, TaskAccessKind } from '@/types/tasks';

import { boardPath } from '../api';
import type { BoardKey } from '../types';
import type { AccessRequest, FeedPage, HistoryItem, PersonOption, RequestsInbox } from './types';

const path = (suffix: string) => apiPath('tasks', suffix);

export interface PlaceBody {
  before_id?: number | null;
  after_id?: number | null;
}

export const checklistsApi = {
  create: async (taskId: number, title: string): Promise<Checklist> =>
    (await api.post<Checklist>(path(`tasks/${taskId}/checklists`), { title })).data,

  update: async (checklistId: number, body: { title?: string } & PlaceBody): Promise<Checklist> =>
    (await api.patch<Checklist>(path(`checklists/${checklistId}`), body)).data,

  remove: async (checklistId: number): Promise<void> => {
    await api.delete(path(`checklists/${checklistId}`));
  },

  addItem: async (checklistId: number, body: { text: string } & PlaceBody): Promise<Checklist> =>
    (await api.post<Checklist>(path(`checklists/${checklistId}/items`), body)).data,

  updateItem: async (itemId: number, body: {
    text?: string;
    is_done?: boolean;
    checklist_id?: number;
  } & PlaceBody): Promise<Checklist> =>
    (await api.patch<Checklist>(path(`checklist-items/${itemId}`), body)).data,

  removeItem: async (itemId: number): Promise<Checklist> =>
    (await api.delete<Checklist>(path(`checklist-items/${itemId}`))).data,
};

export const feedApi = {
  page: async (taskId: number, details: boolean, before: string | null): Promise<FeedPage> =>
    (await api.get<FeedPage>(path(`tasks/${taskId}/feed`), {
      params: { details: details ? '1' : '0', ...(before ? { before } : {}) },
    })).data,
};

export const accessApi = {
  forTask: async (taskId: number): Promise<AccessRequest[]> =>
    (await api.get<AccessRequest[]>(path(`tasks/${taskId}/access-requests`))).data,

  request: async (taskId: number, kind: TaskAccessKind, comment: string): Promise<AccessRequest> =>
    (await api.post<AccessRequest>(path(`tasks/${taskId}/access-requests`), { kind, comment })).data,

  approve: async (requestId: number, body: { mode?: 'replace' | 'delegate'; comment?: string }):
    Promise<AccessRequest> =>
    (await api.post<AccessRequest>(path(`access-requests/${requestId}/approve`), body)).data,

  reject: async (requestId: number, comment: string): Promise<AccessRequest> =>
    (await api.post<AccessRequest>(path(`access-requests/${requestId}/reject`), { comment })).data,

  cancel: async (requestId: number): Promise<void> => {
    await api.delete(path(`access-requests/${requestId}`));
  },

  inbox: async (): Promise<RequestsInbox> =>
    (await api.get<RequestsInbox>(path('access-requests/inbox'))).data,

  history: async (departmentId: number, filters: Record<string, string>):
    Promise<{ items: HistoryItem[] }> =>
    (await api.get<{ items: HistoryItem[] }>(
      path(`boards/departments/${departmentId}/access-history`), { params: filters })).data,
};

export const boardNotificationsApi = {
  set: async (key: BoardKey, enabled: boolean): Promise<{ enabled: boolean }> =>
    (await api.put<{ enabled: boolean }>(path(`${boardPath(key)}/notifications`), { enabled })).data,
};

/** Поиск людей по имени, логину и почте — только действующие участники
 * текущей компании (`GET people`). */
export const peopleApi = {
  search: async (query: string): Promise<PersonOption[]> =>
    (await api.get<PersonOption[]>(path('people'), { params: { query, limit: '20' } })).data,
};

/** Ключи запросов окна карточки (мастер-план §7.2). */
export const cardKeys = {
  card: (taskId: number) => ['tasks', 'card', taskId] as const,
  feed: (taskId: number, details: boolean) => ['tasks', 'feed', taskId, details] as const,
  feedPrefix: (taskId: number) => ['tasks', 'feed', taskId] as const,
  access: (taskId: number) => ['tasks', 'card', taskId, 'access-requests'] as const,
  inbox: () => ['tasks', 'requests', 'inbox'] as const,
  history: (departmentId: number, filters: Record<string, string>) =>
    ['tasks', 'requests', 'history', departmentId, filters] as const,
  people: (query: string) => ['tasks', 'people', query] as const,
};
