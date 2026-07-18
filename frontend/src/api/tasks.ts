/* ------------------------------------------------------------------ */
/*  Tasks module — API helpers                                         */
/* ------------------------------------------------------------------ */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
  Label, Project, Task, TaskComment, TaskAttachment, TaskStats, TaskStatus,
  TaskLink, Notification, TaskAssigneeRef, AssigneeRole, TaskTypeRef,
  Equipment, ResourceGanttResponse, Assignment,
} from '@/types/tasks';

const BASE = `${API_ENDPOINTS.tasks}/`;

/* Unwrap paginated or plain array response */
function unwrap<T>(data: any): T[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  return [];
}

const TASK_FIELD_ALIASES: Record<string, string> = {
  reporter: 'reporter_id',
  assignee: 'assignee_id',
  supervisor: 'supervisor_id',
  department: 'department_id',
  project: 'project_id',
  parent: 'parent_id',
};

const PROJECT_FIELD_ALIASES: Record<string, string> = {
  department: 'department_id',
  owner: 'owner_id',
};

function toBackendRecord(data: Record<string, any>, aliases: Record<string, string>): Record<string, any> {
  const payload: Record<string, any> = {};
  Object.entries(data).forEach(([key, value]) => {
    if (value === undefined || value === '') return;
    payload[aliases[key] ?? key] = value;
  });
  return payload;
}

function normalizeTask(raw: any): Task {
  return {
    ...raw,
    progress_percent: typeof raw.progress_percent === 'number' ? raw.progress_percent : 0,
    reporter: raw.reporter ?? raw.reporter_id,
    reporter_name: raw.reporter_name,
    assignee: raw.assignee ?? raw.assignee_id ?? null,
    assignee_name: raw.assignee_name,
    supervisor: raw.supervisor ?? raw.supervisor_id ?? null,
    supervisor_name: raw.supervisor_name,
    department: raw.department ?? raw.department_id ?? null,
    department_name: raw.department_name,
    department_ids: Array.isArray(raw.department_ids) ? raw.department_ids : [],
    departments: Array.isArray(raw.departments) ? raw.departments : [],
    project: raw.project ?? raw.project_id ?? null,
    project_name: raw.project_name,
    project_color: raw.project_color,
    parent: raw.parent ?? raw.parent_id ?? null,
    parent_key: raw.parent_key,
    assignees: Array.isArray(raw.assignees) ? raw.assignees : [],
    delegates: Array.isArray(raw.delegates) ? raw.delegates : [],
    watchers: Array.isArray(raw.watchers) ? raw.watchers : [],
    subtasks: Array.isArray(raw.subtasks) ? raw.subtasks.map(normalizeTask) : raw.subtasks,
  };
}

function normalizeProject(raw: any): Project {
  return {
    ...raw,
    owner_id: raw.owner_id ?? null,
    owner_name: raw.owner_name,
    department_id: raw.department_id ?? null,
    department_name: raw.department_name,
  };
}

function buildQuery(params?: Record<string, string>, aliases: Record<string, string> = {}): string {
  if (!params) return '';
  const mapped = toBackendRecord(params, aliases);
  return '?' + new URLSearchParams(mapped).toString();
}

/* ---------- Labels ---------- */
export const fetchLabels = async (): Promise<Label[]> => {
  const res = await api.get(`${BASE}labels/`);
  return unwrap<Label>(res.data);
};

export const createLabel = async (data: Partial<Label>): Promise<Label> => {
  const res = await api.post(`${BASE}labels/`, data);
  return res.data;
};

export const updateLabel = async (id: number, data: Partial<Label>): Promise<Label> => {
  const res = await api.patch(`${BASE}labels/${id}/`, data);
  return res.data;
};

export const deleteLabel = async (id: number): Promise<void> => {
  await api.delete(`${BASE}labels/${id}/`);
};

/* ---------- Projects (Roadmap) ---------- */
export const fetchProjects = async (params?: Record<string, string>): Promise<Project[]> => {
  const query = buildQuery(params, PROJECT_FIELD_ALIASES);
  const res = await api.get(`${BASE}projects/${query}`);
  return unwrap<Project>(res.data).map(normalizeProject);
};

export const fetchProject = async (id: number): Promise<Project> => {
  const res = await api.get(`${BASE}projects/${id}/`);
  return normalizeProject(res.data);
};

export const createProject = async (data: Partial<Project>): Promise<Project> => {
  const res = await api.post(`${BASE}projects/`, toBackendRecord(data as Record<string, any>, PROJECT_FIELD_ALIASES));
  return normalizeProject(res.data);
};

export const updateProject = async (id: number, data: Partial<Project>): Promise<Project> => {
  const res = await api.patch(`${BASE}projects/${id}/`, toBackendRecord(data as Record<string, any>, PROJECT_FIELD_ALIASES));
  return normalizeProject(res.data);
};

export const deleteProject = async (id: number): Promise<void> => {
  await api.delete(`${BASE}projects/${id}/`);
};

export const fetchProjectTasks = async (id: number): Promise<Task[]> => {
  const res = await api.get(`${BASE}projects/${id}/tasks/`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

/* ---------- Task types (registry) ---------- */
export const fetchTaskTypes = async (): Promise<TaskTypeRef[]> => {
  const res = await api.get(`${BASE}task-types/`);
  return unwrap<TaskTypeRef>(res.data);
};

export const createTaskType = async (data: { name: string; slug?: string; color?: string; icon?: string | null }): Promise<TaskTypeRef> => {
  const res = await api.post(`${BASE}task-types/`, data);
  return res.data;
};

export const updateTaskType = async (id: number, data: Partial<{ name: string; color: string; icon: string | null }>): Promise<TaskTypeRef> => {
  const res = await api.patch(`${BASE}task-types/${id}/`, data);
  return res.data;
};

export const deleteTaskType = async (id: number): Promise<void> => {
  await api.delete(`${BASE}task-types/${id}/`);
};

/* ---------- Tasks ---------- */
export const fetchTasks = async (params?: Record<string, string>): Promise<Task[]> => {
  const query = buildQuery(params, TASK_FIELD_ALIASES);
  const res = await api.get(`${BASE}tasks/${query}`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

export const fetchTask = async (id: number): Promise<Task> => {
  const res = await api.get<Task>(`${BASE}tasks/${id}/`);
  return normalizeTask(res.data);
};

export const fetchTaskTransitions = async (id: number): Promise<TaskStatus[]> => {
  const res = await api.get<TaskStatus[]>(`${BASE}tasks/${id}/transitions/`);
  return res.data;
};

export const createTask = async (data: Partial<Task>): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/`, toBackendRecord(data as Record<string, any>, TASK_FIELD_ALIASES));
  return normalizeTask(res.data);
};

export const updateTask = async (id: number, data: Partial<Task>): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${id}/`, toBackendRecord(data as Record<string, any>, TASK_FIELD_ALIASES));
  return normalizeTask(res.data);
};

export const deleteTask = async (id: number): Promise<void> => {
  await api.delete(`${BASE}tasks/${id}/`);
};

export const fetchTaskStats = async (params?: Record<string, string>): Promise<TaskStats> => {
  const query = buildQuery(params, TASK_FIELD_ALIASES);
  const res = await api.get(`${BASE}tasks/stats/${query}`);
  return res.data;
};

/* ---------- Multi-assignee / supervisor / delegates / watchers / progress --- */

/** Replace the task's assignee crew (primary + collaborators). */
export const updateTaskAssignees = async (
  taskId: number,
  assignees: Array<{ user_id: number; role: AssigneeRole }>,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/assignees/`, { assignees });
  return normalizeTask(res.data);
};

/** Set or clear the task supervisor (single user). */
export const updateTaskSupervisor = async (
  taskId: number,
  userId: number | null,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/supervisor/`, { user_id: userId });
  return normalizeTask(res.data);
};

/** Grant a user delegate (deputy) rights — supervisor-only on the backend. */
export const addTaskDelegate = async (taskId: number, userId: number): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/${taskId}/delegates/`, { user_id: userId });
  return normalizeTask(res.data);
};

export const removeTaskDelegate = async (taskId: number, userId: number): Promise<Task> => {
  const res = await api.delete(`${BASE}tasks/${taskId}/delegates/${userId}/`);
  return normalizeTask(res.data);
};

/** Follow/unfollow a task (self-subscribe). */
export const watchTask = async (taskId: number): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/${taskId}/watch/`);
  return normalizeTask(res.data);
};

export const unwatchTask = async (taskId: number): Promise<Task> => {
  const res = await api.delete(`${BASE}tasks/${taskId}/watch/`);
  return normalizeTask(res.data);
};

/** Set the progress percent (0..100). */
export const updateTaskProgress = async (
  taskId: number,
  percent: number,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/progress/`, { percent });
  return normalizeTask(res.data);
};

/* ---------- Resource planning (Gantt) ---------- */
export const fetchResourceGantt = async (params: {
  from: string;
  to: string;
  kinds?: string;
  department_id?: number;
  search?: string;
}): Promise<ResourceGanttResponse> => {
  const res = await api.get(`${BASE}reports/resource-gantt`, { params });
  return res.data;
};

export const fetchEquipment = async (activeOnly = true): Promise<Equipment[]> => {
  const res = await api.get(`${BASE}equipment/`, { params: { active_only: activeOnly } });
  return unwrap<Equipment>(res.data);
};

export const createEquipment = async (data: Partial<Equipment>): Promise<Equipment> => {
  const res = await api.post(`${BASE}equipment/`, data);
  return res.data;
};

export const updateEquipment = async (id: number, data: Partial<Equipment>): Promise<Equipment> => {
  const res = await api.patch(`${BASE}equipment/${id}/`, data);
  return res.data;
};

export const deleteEquipment = async (id: number): Promise<void> => {
  await api.delete(`${BASE}equipment/${id}/`);
};

/* ---------- Task assignments (resources on a task) ---------- */
export const fetchAssignments = async (taskId: number): Promise<Assignment[]> => {
  const res = await api.get(`${BASE}assignments/`, { params: { task_id: taskId } });
  return unwrap<Assignment>(res.data);
};

export const createAssignment = async (data: {
  task_id: number;
  employee_id?: number;
  equipment_id?: number;
  role?: string;
  allocation?: number;
}): Promise<Assignment> => {
  const res = await api.post(`${BASE}assignments/`, data);
  return res.data;
};

export const deleteAssignment = async (id: number): Promise<void> => {
  await api.delete(`${BASE}assignments/${id}/`);
};

export const addTaskComment = async (taskId: number, body: string): Promise<TaskComment> => {
  const res = await api.post(`${BASE}tasks/${taskId}/comments/`, { body });
  return res.data;
};

export const addTaskAttachment = async (taskId: number, file: File): Promise<TaskAttachment> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post(`${BASE}tasks/${taskId}/attachments/`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};
/* ---------- Task Links ---------- */
export const createTaskLink = async (data: { source: number; target: number; link_type: string }): Promise<TaskLink> => {
  const res = await api.post(`${BASE}task-links/`, data);
  return res.data;
};

export const deleteTaskLink = async (id: number): Promise<void> => {
  await api.delete(`${BASE}task-links/${id}/`);
};

/* ---------- Notifications ---------- */
export const fetchNotifications = async (): Promise<Notification[]> => {
  const res = await api.get(`${BASE}notifications/`);
  return unwrap<Notification>(res.data);
};

export interface NotificationHistoryParams {
  page?: number;
  limit?: number;
  /** "all" omits the filter; "unread" / "read" narrow the query. */
  status?: 'all' | 'unread' | 'read';
  target_type?: string;
}

export const fetchNotificationHistory = async (
  params: NotificationHistoryParams = {},
): Promise<import('@/types/tasks').NotificationsPage> => {
  const q = new URLSearchParams();
  if (params.page) q.append('page', String(params.page));
  if (params.limit) q.append('limit', String(params.limit));
  if (params.status) q.append('status', params.status);
  if (params.target_type) q.append('target_type', params.target_type);
  const res = await api.get<import('@/types/tasks').NotificationsPage>(
    `${BASE}notifications/history/?${q.toString()}`,
  );
  return res.data;
};

export const markNotificationRead = async (id: number): Promise<void> => {
  await api.post(`${BASE}notifications/${id}/mark_read/`);
};

export const markNotificationUnread = async (id: number): Promise<void> => {
  await api.post(`${BASE}notifications/${id}/mark_unread/`);
};

export const markAllNotificationsRead = async (): Promise<void> => {
  await api.post(`${BASE}notifications/mark-all-read/`);
};

export const deleteNotification = async (id: number): Promise<void> => {
  await api.delete(`${BASE}notifications/${id}/`);
};

/**
 * Build the SPA URL for a notification's target. Returns ``null`` when
 * the row has no clickable destination (e.g. system messages without a
 * concrete entity reference).
 */
export const notificationTargetUrl = (
  n: Pick<Notification, 'target_type' | 'target_id' | 'task' | 'verb'>,
): string | null => {
  if (n.target_type === 'task' && n.target_id) return `/tasks/${n.target_id}`;
  if (n.target_type === 'calendar_event' && n.target_id)
    return `/calendar?event=${n.target_id}`;
  if (n.target_type === 'employee' && n.target_id)
    return `/hr/employees/${n.target_id}`;
  if (n.target_type === 'messenger_room' && n.target_id)
    return `/messenger?room=${n.target_id}`;
  if (n.target_type === 'email_message') return `/email`;
  // Legacy: rows that only set the ``task_id`` FK column.
  if (n.task) return `/tasks/${n.task}`;
  // Legacy verb format: pull the entity id out so old rows are still
  // clickable. Patterns we recognise:
  //   calendar_invited:event:<id>:<title>
  //   calendar_updated:event:<id>:<title>
  const verb = n.verb || '';
  const calMatch = verb.match(/^calendar_(?:invited|updated):event:(\d+):/);
  if (calMatch) return `/calendar?event=${calMatch[1]}`;
  return null;
};

/** Human-readable source label rendered as a chip next to the notification. */
export const notificationSourceLabel = (
  n: Pick<Notification, 'target_type' | 'task' | 'verb'>,
): string | null => {
  if (n.target_type === 'task' || n.task) return 'Задача';
  if (n.target_type === 'calendar_event') return 'Календарь';
  if (n.target_type === 'employee') return 'HR';
  if (n.target_type === 'messenger_room') return 'Мессенджер';
  if (n.target_type === 'email_message') return 'Почта';
  // Legacy verb fallback — same patterns as notificationTargetUrl.
  const verb = n.verb || '';
  if (/^calendar_(?:invited|updated):event:/.test(verb)) return 'Календарь';
  if (/^task_(?:due|assigned|commented)/.test(verb)) return 'Задача';
  return null;
};

/**
 * Convert a notification's ``verb`` (free-form, may be a legacy
 * machine-encoded string like ``calendar_invited:event:42:Совещание``)
 * into a single human-readable sentence ready to render in the UI.
 *
 * New events emitted by the backend already arrive as natural language,
 * so this function is mostly a safety net for historical rows. Once those
 * have aged out the function still trivially returns the verb as-is.
 */
export const formatNotificationText = (n: Pick<Notification, 'verb'>): string => {
  const verb = (n.verb || '').trim();
  if (!verb) return 'Уведомление';

  // Legacy calendar invite: ``calendar_invited:event:<id>:<title>``
  const calMatch = verb.match(/^calendar_invited:event:\d+:(.+)$/);
  if (calMatch) return `пригласил(а) на событие «${calMatch[1]}»`;

  const calUpdMatch = verb.match(/^calendar_updated:event:\d+:(.+)$/);
  if (calUpdMatch) return `обновил(а) событие «${calUpdMatch[1]}»`;

  // Legacy task-deadline verb: ``task_due_2d`` / ``task_due_0d``
  const dueMatch = verb.match(/^task_due_(-?\d+)d$/);
  if (dueMatch) {
    const days = Number(dueMatch[1]);
    if (days === 0) return 'дедлайн сегодня';
    if (days < 0) return `дедлайн просрочен на ${Math.abs(days)} д.`;
    return `до дедлайна ${days} д.`;
  }

  // Legacy chat-notification verbs that still mention "прислал" — drop the
  // preamble so all UI surfaces read uniformly. New rows already arrive
  // without this prefix.
  const chatLegacy = verb.match(
    /^прислал(?:\s+(?:в чате «[^»]*»|сообщение))?:\s*(.+)$/,
  );
  if (chatLegacy) return chatLegacy[1].trim();

  return verb;
};
