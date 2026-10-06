/**
 * Клиент проектной структуры (`/api/project/v1`, спек
 * docs/plans/2026-10-06-project-structure-spec.md §4; сервер —
 * `apps/project/views_structure.py`).
 *
 * Структура своя у каждого проекта и не связана с кадровой схемой: роли —
 * справочник компании (L1–L4), места — с руководителем-местом и планом
 * людей, назначения — сотрудник на месте с даты по дату. Можно ли править,
 * говорит сервер (`can_edit`: руководитель своего проекта или держатель
 * `project.structure`) — экран кнопки по нему и показывает.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type ProjectPart = 'office' | 'site';

export interface ProjectRole {
  id: number;
  name: string;
  level: number;
  default_part: ProjectPart;
  sort_order: number;
  is_active: boolean;
}

export interface StructureAssignment {
  id: string;
  employee_id: number;
  full_name: string;
  position_title: string;
  date_from: string;
  date_to: string | null;
  /** Уволен или удалён из кадров — на схеме помечается, а не пропадает. */
  dismissed: boolean;
}

export interface StructureSlot {
  id: string;
  role: { id: number; name: string; level: number };
  part: ProjectPart;
  title: string;
  parent_id: string | null;
  planned_headcount: number;
  actual_headcount: number;
  closed_on: string | null;
  assignments: StructureAssignment[];
}

export interface ProjectStructure {
  project_id: string;
  on: string;
  can_edit: boolean;
  slots: StructureSlot[];
}

export interface EmployeeOption {
  id: number;
  full_name: string;
  position_title: string;
}

export interface SlotCreate {
  role_id: number;
  parent_id: string | null;
  part: ProjectPart;
  title: string;
  planned_headcount: number;
}

export interface SlotPatch {
  parent_id?: string | null;
  part?: ProjectPart;
  title?: string;
  planned_headcount?: number;
  closed_on?: string;
}

export interface RoleCreate {
  name: string;
  level: number;
  default_part: ProjectPart;
  sort_order: number;
}

const p = (suffix: string) => apiPath('project', suffix);

export const structureKeys = {
  structure: (projectId: string, on: string) => ['project', 'structure', projectId, on] as const,
  allOf: (projectId: string) => ['project', 'structure', projectId] as const,
  roles: (activeOnly: boolean) => ['project', 'roles', { activeOnly }] as const,
  rolesAll: ['project', 'roles'] as const,
  employees: (q: string) => ['project', 'employees', q] as const,
};

export const structureApi = {
  structure: (projectId: string, on: string) =>
    api.get<ProjectStructure>(p(`projects/${projectId}/structure`), { params: { on } })
      .then((r) => r.data),
  roles: (activeOnly = false) =>
    api.get<ProjectRole[]>(p('project-roles'), { params: activeOnly ? { active: 1 } : {} })
      .then((r) => r.data),
  createRole: (body: RoleCreate) =>
    api.post<ProjectRole>(p('project-roles'), body).then((r) => r.data),
  updateRole: (id: number, body: Partial<RoleCreate> & { is_active?: boolean }) =>
    api.patch<ProjectRole>(p(`project-roles/${id}`), body).then((r) => r.data),
  deleteRole: (id: number) => api.delete(p(`project-roles/${id}`)).then(() => undefined),
  createSlot: (projectId: string, body: SlotCreate) =>
    api.post<{ id: string }>(p(`projects/${projectId}/slots`), body).then((r) => r.data),
  updateSlot: (slotId: string, body: SlotPatch) =>
    api.patch<{ id: string }>(p(`slots/${slotId}`), body).then((r) => r.data),
  assign: (slotId: string, body: { employee_id: number; date_from: string; date_to?: string | null }) =>
    api.post<{ id: string }>(p(`slots/${slotId}/assignments`), body).then((r) => r.data),
  endAssignment: (id: string, dateTo: string) =>
    api.patch<{ id: string }>(p(`assignments/${id}`), { date_to: dateTo }).then((r) => r.data),
  deleteAssignment: (id: string) => api.delete(p(`assignments/${id}`)).then(() => undefined),
  employees: (q: string) =>
    api.get<EmployeeOption[]>(p('employees'), { params: { q } }).then((r) => r.data),
};

/** Сегодня в формате ISO по местному времени — дата схемы по умолчанию. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export const LEVELS = [1, 2, 3, 4] as const;

/** Подпись места: роль и уточнение («Специалист — сметчик»). */
export function slotLabel(slot: StructureSlot): string {
  return slot.title ? `${slot.role.name} — ${slot.title}` : slot.role.name;
}
