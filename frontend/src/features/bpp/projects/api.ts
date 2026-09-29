/**
 * Клиент «Проекта» (`/api/project/v1`, D-02; сервер — `apps/project`).
 *
 * Видимость решает сервер: без узла `project.all` (у ПМ его нет) список,
 * карточка и участники ограничены проектами, где вызывающий участник, чужой
 * проект — 404. Экран показывает ровно то, что пришло, и сам не фильтрует.
 *
 * Список — голый массив (не конверт реестров B), без архивных, до 200
 * строк: проектов у компании десятки, серверной пагинации ручка не даёт.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type ProjectKind = 'project' | 'company_overhead';
export type ProjectStatus = 'active' | 'closed' | 'archived';

export interface Project {
  id: string;
  code: string;
  name: string;
  kind: ProjectKind;
  status: ProjectStatus;
  country_code: string;
  manager_user_id: number | null;
  customer_name: string;
  customer_counterparty_id: string | null;
}

export interface ProjectCreate {
  code: string;
  name: string;
  kind: ProjectKind;
  country_code: string;
  manager_user_id: number | null;
  customer_name: string;
  /** Заказчик — контрагент из реестра; пустая строка — не выбран (так его
   * принимает сервер: `ProjectIn.customer_counterparty_id: str = ""`). */
  customer_counterparty_id: string;
  date_start: string | null;
  date_end: string | null;
}

export interface ProjectPatch {
  name?: string;
  status?: ProjectStatus;
  manager_user_id?: number | null;
  customer_name?: string;
  /** Пустая строка снимает выбор. */
  customer_counterparty_id?: string;
}

const path = (suffix = '') => apiPath('project', suffix ? `projects/${suffix}` : 'projects');

export const PROJECTS_BASE = '/bpp/projects';
export const projectHref = (id: string) => `${PROJECTS_BASE}/${id}`;

export const projectKeys = {
  list: (q: string, mine: boolean) => ['project', 'projects', { q, mine }] as const,
  all: ['project', 'projects'] as const,
  card: (id: string) => ['project', 'project', id] as const,
  members: (id: string) => ['project', 'members', id] as const,
};

export const projectApi = {
  list: (q: string, mine: boolean) =>
    api.get<Project[]>(path(), {
      params: { ...(q ? { q } : {}), ...(mine ? { mine: 1 } : {}) },
    }).then((r) => r.data),
  get: (id: string) => api.get<Project>(path(id)).then((r) => r.data),
  create: (body: ProjectCreate) => api.post<Project>(path(), body).then((r) => r.data),
  update: (id: string, body: ProjectPatch) => api.patch<Project>(path(id), body).then((r) => r.data),
  members: (id: string) => api.get<number[]>(path(`${id}/members`)).then((r) => r.data),
  addMember: (id: string, userId: number) =>
    api.post<{ user_id: number }>(path(`${id}/members`), { user_id: userId }).then((r) => r.data),
  removeMember: (id: string, userId: number) =>
    api.delete(path(`${id}/members/${userId}`)).then(() => undefined),
};
